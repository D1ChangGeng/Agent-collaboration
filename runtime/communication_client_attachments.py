"""Viewer-private uploads and message-authorized downloads over the existing CAS.

Each callback below ends its authenticated SQL transaction before any incoming
stream or CAS access. Internal plans bind HTTP idempotency to the first captured
lease/revision; retries do not recompute those inputs from a newer resource.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from runtime import communication_attachment_storage as storage
from runtime.communication_attachment_content import (
    AttachmentContentError,
    attachment_content_disposition,
    normalize_attachment_media_type,
    put_attachment_content,
    read_attachment_content,
    validate_attachment_name,
)
from runtime.communication_attachment_policy import attachment_owner
from runtime.communication_http import CommunicationHttpError
from runtime.errors import (
    AuthorizationDenied,
    IdempotencyConflict,
    InvalidToolArgument,
    NotFound,
    RevisionConflict,
    SchemaAdoptionError,
)


def attachment_failure(error, *, effect_state="none", read_only=False):
    """Only implementation-owned public text crosses the attachment boundary."""
    options = {}
    if isinstance(error, CommunicationHttpError):
        return CommunicationHttpError(error.code, error.message, status_code=error.status_code,
            retryable=error.retryable, effect_state=effect_state, operation_ref=error.operation_ref,
            details=error.details, retry_after=error.retry_after)
    if isinstance(error, AttachmentContentError):
        code, message, status = error.code, error.message, error.status_code
    elif isinstance(error, storage.AttachmentQuotaExceeded):
        code, message, status = error.code, "Attachment reservation budget exceeded.", 429
        options = {"retryable": True, "retry_after": 5}
    elif isinstance(error, storage.AttachmentExpired):
        code, message, status = error.code, "Attachment reservation expired.", 410
    elif isinstance(error, storage.AttachmentUploadConflict):
        code, message, status = error.code, "Attachment upload state or bytes conflict.", 409
    elif isinstance(error, storage.AttachmentCorrupt):
        code, message, status = "attachment_content_unavailable", "Attachment integrity is unavailable.", 503
    elif isinstance(error, PermissionError):
        code, message, status = "unauthenticated", "Trusted bearer authentication is required.", 401
    elif isinstance(error, AuthorizationDenied):
        code, message, status = "authorization_denied", "This action is not authorized.", 403
    elif isinstance(error, NotFound):
        code, message, status = "not_found", "Resource not found or not visible.", 404
    elif isinstance(error, (IdempotencyConflict, RevisionConflict)):
        code = "idempotency_conflict" if isinstance(error, IdempotencyConflict) else "revision_conflict"
        message, status = "Request identity or version conflicts with the current state.", 409
    elif isinstance(error, SchemaAdoptionError):
        code, message, status = "schema_adoption_required", "Attachment storage requires explicit adoption.", 503
    elif isinstance(error, (InvalidToolArgument, ValueError, TypeError)):
        code, message, status = "invalid_argument", "Invalid attachment request.", 400
    else:
        code, message, status = "attachment_service_unavailable", "Attachment service is unavailable.", 503
        effect_state = "unknown" if effect_state == "none" and not read_only else effect_state
    return CommunicationHttpError(code, message, status_code=status, effect_state=effect_state, **options)


@dataclass(frozen=True, slots=True)
class AttachmentUploadContext:
    project: str
    attachment_id: str
    owner: storage.AttachmentIdentity
    lease: storage.UploadLease
    attachment: dict
    namespace: str
    content_type: str
    prior_result: dict | None


@dataclass(frozen=True, slots=True)
class AttachmentDownload:
    data: bytes
    media_type: str
    content_disposition: str
    sha256: str


class ClientAttachmentService:
    def _attachment_limits(self):
        settings = getattr(self.authority, "_communication_attachment_settings", None)
        if settings is None or not getattr(self.authority, "_communication_attachments_enabled", False):
            raise CommunicationHttpError("capability_unsupported", "Attachments are not enabled.", status_code=409)
        return settings.to_limits()

    def _attachment_owner(self, bound, cursor, root, project):
        address = self.project_service._communication_address(cursor, project)
        return attachment_owner(cursor, bound.context, project, address, root[0])

    def _attachment_store(self, scope, *, required_bytes=1):
        stores = self.project_service.artifacts
        try:
            store = stores.for_scope(scope) if callable(getattr(stores, "for_scope", None)) else stores
            if store is None or store.scope_id != scope or store.max_bytes < required_bytes:
                raise ValueError("attachment CAS capacity is unavailable")
            return store
        except Exception as error:
            raise CommunicationHttpError("capability_unsupported", "An admitted Scope attachment store is unavailable.", status_code=409) from error

    def _attachment_tx(self, project, callback, *, write=False, expected_owner=None):
        limits = self._attachment_limits()

        def selected(bound, cursor, root, command):
            owner = self._attachment_owner(bound, cursor, root, project)
            if expected_owner is not None and owner != expected_owner:
                raise AuthorizationDenied(bound.context.principal_ref, bound.context.grant_ref)
            if write:
                bound._authorize(command, cursor, "artifact.write", owner.scope_id)
                self._attachment_store(owner.scope_id, required_bytes=limits.file_bytes)
            value = callback(bound, cursor, owner, limits, command)
            if write:
                bound._authorize(command, cursor, "artifact.write", owner.scope_id)
            return value
        try:
            return self._transaction(project, "send_message" if write else "read_message", selected)
        except CommunicationHttpError:
            raise
        except Exception as error:
            raise attachment_failure(error, read_only=not write) from error

    def create_attachment(self, project, body, *, client_request_id):
        try:
            body = self._validate("AttachmentCreate", body)
            declaration = body | {"name": validate_attachment_name(body["name"]),
                                  "media_type": normalize_attachment_media_type(body["media_type"])}
        except Exception as error:
            raise attachment_failure(error, read_only=True) from error
        def selected(_bound, cursor, owner, limits, _command):
            if declaration["bytes"] > limits.file_bytes:
                raise CommunicationHttpError("content_too_large", "Attachment exceeds the advertised per-file byte limit.", status_code=413)
            key = self._private_request_key(project, owner.owner_address, "attachment-reserve", client_request_id)
            return storage.reserve_attachment(cursor, owner, declaration, key, limits=limits)
        return self._validate("Attachment", self._attachment_tx(project, selected, write=True))

    def _attachment_visible(self, cursor, owner, attachment_id):
        try:
            return storage.get_attachment(cursor, owner, attachment_id), None
        except NotFound:
            pass
        cursor.execute("SELECT m.message_id FROM communication_message_attachments m JOIN communication_messages c "
            "USING(tenant_id,project_id,message_id) WHERE m.tenant_id=%s AND m.project_id=%s AND m.attachment_id=%s "
            "AND (c.sender=%s OR c.recipient=%s) ORDER BY m.message_id LIMIT 1",
            (owner.tenant_id, owner.project_id, attachment_id, owner.owner_address, owner.owner_address))
        found = cursor.fetchone()
        if found is None:
            raise NotFound("attachment", attachment_id)
        reference, artifact = storage.message_attachment_artifact(cursor, owner.tenant_id, owner.project_id,
            owner.owner_address, found[0], attachment_id)
        cursor.execute("SELECT revision FROM communication_attachments WHERE tenant_id=%s AND project_id=%s AND attachment_id=%s",
                       (owner.tenant_id, owner.project_id, attachment_id))
        return {**reference, "project_id": owner.project_id, "state": "ready", "upload_path": None,
                "expires_at": None, "revision": cursor.fetchone()[0]}, artifact

    def attachment(self, project, attachment_id):
        value = self._attachment_tx(project, lambda _b, cur, owner, _l, _c: self._attachment_visible(cur, owner, attachment_id)[0])
        return self._validate("Attachment", value)

    def begin_attachment_upload(self, project, attachment_id, *, content_type, client_request_id):
        try:
            content_type = normalize_attachment_media_type(content_type)
        except Exception as error:
            raise attachment_failure(error) from error
        def selected(_bound, cursor, owner, limits, _command):
            key = self._private_request_key(project, owner.owner_address, "attachment-upload:" + attachment_id, client_request_id)
            body = [attachment_id, content_type]
            def prepare(cur):
                value = storage.get_attachment(cur, owner, attachment_id)
                if content_type != "application/octet-stream":
                    raise AttachmentContentError("Upload content as application/octet-stream.")
                lease = storage.begin_attachment_upload(cur, owner, attachment_id, expected_revision=value["revision"],
                    request_namespace=key + "-begin", restart=value["revision"] > 1, limits=limits)
                return {"attachment": value, "lease": asdict(lease)}
            plan = storage.attachment_request(cursor, owner, attachment_id, key + "-plan", "upload_plan", body, prepare)
            prior = storage.attachment_request(cursor, owner, attachment_id, key + "-result", "upload_result", body)
            return AttachmentUploadContext(project, attachment_id, owner, storage.UploadLease(**plan["lease"]),
                plan["attachment"], key, content_type, prior)
        return self._attachment_tx(project, selected, write=True)

    def append_attachment_upload(self, context, offset, data):
        def selected(_bound, cursor, owner, _limits, _command):
            if context.prior_result is not None:
                storage.get_attachment(cursor, owner, context.attachment_id)
                return None
            return storage.append_attachment_chunk(cursor, owner, context.attachment_id, context.lease, offset, data)
        return self._attachment_tx(context.project, selected, write=True, expected_owner=context.owner)

    def complete_attachment_upload(self, context, *, observed_bytes, observed_sha256, last_revision):
        """The HTTP stream supplies its actual digest, including duplicate bodies."""
        def selected(_bound, cursor, owner, _limits, _command):
            body = [context.attachment_id, context.content_type]
            def complete(cur):
                if (observed_bytes, observed_sha256) != (context.attachment["bytes"], context.attachment["sha256"]):
                    storage.reject_attachment(cur, owner, context.attachment_id, expected_revision=last_revision,
                                              request_namespace=context.namespace + "-reject")
                    return {"observed_bytes": observed_bytes, "observed_sha256": observed_sha256,
                            "error": {"code": "invalid_argument", "message": "Uploaded size or SHA-256 differs from its reservation.", "status": 400}}
                value = storage.complete_attachment_upload(cur, owner, context.attachment_id, context.lease, context.namespace + "-complete")
                return {"observed_bytes": observed_bytes, "observed_sha256": observed_sha256, "attachment": value}
            return storage.attachment_request(cursor, owner, context.attachment_id, context.namespace + "-result", "upload_result", body, complete)
        try:
            value = self._attachment_tx(context.project, selected, write=True, expected_owner=context.owner)
            if (value["observed_bytes"], value["observed_sha256"]) != (observed_bytes, observed_sha256):
                raise CommunicationHttpError("idempotency_conflict", "Upload bytes differ from the original request.", status_code=409)
            if "error" in value:
                issue = value["error"]
                raise CommunicationHttpError(issue["code"], issue["message"], status_code=issue["status"])
            return self._validate("Attachment", value["attachment"])
        except Exception as error:
            raise attachment_failure(error, effect_state="committed") from error

    def _finalize_attachment_outcome(self, value):
        if "error" in value:
            issue = value["error"]
            raise CommunicationHttpError(issue["code"], issue["message"], status_code=issue["status"], effect_state="committed")
        return self._validate("Attachment", value["attachment"])

    def _attachment_ready_result(self, project, owner, attachment_id, key, request):
        """Converge concurrent finalizers only on the same immutable ready ID."""
        def selected(_bound, cursor, actual, _limits, _command):
            prior = storage.attachment_request(cursor, actual, attachment_id, key + "-result", "finalize_result", request)
            if prior is not None:
                return prior
            current = storage.get_attachment(cursor, actual, attachment_id)
            if current["state"] != "ready":
                return None
            return storage.attachment_request(cursor, actual, attachment_id, key + "-result", "finalize_result", request,
                                              lambda _cur: {"attachment": current})
        return self._attachment_tx(project, selected, write=True, expected_owner=owner)

    def finalize_attachment(self, project, attachment_id, body, *, client_request_id):
        committed = False
        try:
            body = self._validate("AttachmentFinalize", body)
            def prepared(_bound, cursor, owner, _limits, _command):
                key = self._private_request_key(project, owner.owner_address, "attachment-finalize:" + attachment_id, client_request_id)
                request = [attachment_id, body]
                def prepare(cur):
                    value = storage.get_attachment(cur, owner, attachment_id)
                    if (value["bytes"], value["sha256"]) != (body["bytes"], body["sha256"]):
                        raise AttachmentContentError("Finalize declaration differs from its reservation.")
                    if value["state"] == "ready":
                        return {"ready": value}
                    lease = storage.uploaded_attachment_lease(cur, owner, attachment_id)
                    return {"attachment": value, "lease": asdict(lease), "revision": value["revision"]}
                plan = storage.attachment_request(cursor, owner, attachment_id, key + "-plan", "finalize_plan", request, prepare)
                prior = storage.attachment_request(cursor, owner, attachment_id, key + "-result", "finalize_result", request)
                return owner, key, request, plan, prior
            owner, key, request, plan, prior = self._attachment_tx(project, prepared, write=True)
            committed = True
            if prior is not None:
                return self._finalize_attachment_outcome(prior)
            ready_result = self._attachment_ready_result(project, owner, attachment_id, key, request)
            if ready_result is not None:
                return self._finalize_attachment_outcome(ready_result)
            if "ready" in plan:
                raise storage.AttachmentExpired("ready reservation expired before the new finalize result")
            lease = storage.UploadLease(**plan["lease"])
            uploaded = self._attachment_tx(project, lambda _b, cur, actual, _l, _c:
                storage.read_uploaded_attachment(cur, actual, attachment_id, lease, expected_revision=plan["revision"]),
                write=True, expected_owner=owner)
            declaration = uploaded.attachment
            store = self._attachment_store(owner.scope_id, required_bytes=declaration["bytes"])
            try:
                artifact = put_attachment_content(store, uploaded.data, expected_scope=owner.scope_id,
                    declared_bytes=declaration["bytes"], declared_sha256=declaration["sha256"], media_type=declaration["media_type"],
                    max_bytes=self._attachment_limits().file_bytes)
            except AttachmentContentError as failure:
                if failure.status_code >= 500:
                    raise
                public_issue = {"code": failure.code, "message": failure.message, "status": failure.status_code}
                def rejected(_b, cursor, actual, _l, _c):
                    def reject(cur):
                        storage.reject_attachment(cur, actual, attachment_id, expected_revision=plan["revision"],
                                                  request_namespace=key + "-reject")
                        return {"error": public_issue}
                    return storage.attachment_request(cursor, actual, attachment_id, key + "-result", "finalize_result", request, reject)
                return self._finalize_attachment_outcome(self._attachment_tx(project, rejected, write=True, expected_owner=owner))
            def finish(_bound, cursor, actual, _limits, _command):
                return storage.attachment_request(cursor, actual, attachment_id, key + "-result", "finalize_result", request,
                    lambda cur: {"attachment": storage.finish_attachment_ready(cur, actual, attachment_id, lease, artifact,
                        expected_revision=plan["revision"], request_namespace=key + "-ready")})
            return self._finalize_attachment_outcome(self._attachment_tx(project, finish, write=True, expected_owner=owner))
        except Exception as error:
            if committed and isinstance(error, CommunicationHttpError) and error.code in {"revision_conflict", "attachment_upload_conflict"}:
                try:
                    ready_result = self._attachment_ready_result(project, owner, attachment_id, key, request)
                    if ready_result is not None:
                        return self._finalize_attachment_outcome(ready_result)
                except Exception as reconciliation_error:
                    raise attachment_failure(reconciliation_error, effect_state="committed") from reconciliation_error
            raise attachment_failure(error, effect_state="committed" if committed else "none") from error

    def download_attachment(self, project, attachment_id):
        def selected(bound, cursor, owner, _limits, command):
            metadata, artifact = self._attachment_visible(cursor, owner, attachment_id)
            if artifact is None:
                bound._authorize(command, cursor, "artifact.read", owner.scope_id)
                artifact = storage.owner_artifact(cursor, owner, attachment_id)
            else:
                # Explicit message association supplies this immutable blob's
                # sharing ACL; it does not grant arbitrary Source Scope reads.
                bound._authorize(command, cursor, "artifact.read")
            return owner, metadata, artifact
        owner, metadata, artifact = self._attachment_tx(project, selected)
        try:
            store = self._attachment_store(artifact.scope_id, required_bytes=metadata["bytes"])
            data = read_attachment_content(store, artifact, expected_scope=artifact.scope_id, declared_bytes=metadata["bytes"],
                declared_sha256=metadata["sha256"], media_type=metadata["media_type"], max_bytes=storage.MAX_FILE)
            current_owner, current_metadata, current_artifact = self._attachment_tx(project, selected, expected_owner=owner)
            if current_owner != owner or current_artifact != artifact or any(current_metadata[key] != metadata[key]
                    for key in ("attachment_id", "name", "media_type", "bytes", "sha256")):
                raise storage.AttachmentCorrupt("attachment binding changed during byte read")
            return AttachmentDownload(data, metadata["media_type"], attachment_content_disposition(metadata["name"]), metadata["sha256"])
        except Exception as error:
            raise attachment_failure(error, read_only=True) from error
