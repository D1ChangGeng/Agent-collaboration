"""Authenticated personal state on existing direct-message conversation views.

This mixin uses the hosting CommunicationClientService transaction so live
credential, caller binding and Project ACL checks surround every operation.
Conversation membership is established from the caller's actual message pairs;
management roles never receive another participant's private state. No method
dispatches Native input, consumes a message or links a reply.
"""
from __future__ import annotations

import re

from runtime import communication_attachment_storage as attachment_storage
from runtime.communication_client_attachments import attachment_failure
from runtime.communication_client_queries import conversation_view_id
from runtime.communication_client_storage import (
    MAX_DRAFT_BYTES,
    ClientStateIdentity,
    delete_draft,
    read_draft,
    read_preferences,
    read_read_state,
    write_draft,
    write_preferences,
    write_read_state,
)
from runtime.communication_client_viewer_storage import require_personal_owner
from runtime.communication_http import CommunicationHttpError
from runtime.errors import InvalidToolArgument, NotFound
from runtime.project_common import parse_handle

_VIEW = re.compile(r"conversation-[a-f0-9]{64}\Z")


class ClientStateService:
    """Personal-state mixin; the host supplies _transaction and _validate."""

    def _prepare_conversation_write(self, cursor, owner, address, peer):
        if (getattr(self.authority, "_communication_conversation_storage_available", False)
                or getattr(self.authority, "_communication_events_enabled", False)):
            from runtime.communication_conversation_storage import prepare_conversation_write

            prepare_conversation_write(cursor, owner, address, peer)

    def _state_actor(self, bound, cursor, project, conversation):
        address = self.project_service._communication_address(cursor, project)
        return ClientStateIdentity(bound.tenant_id, project,
                                   self._viewer_actor_ref(project, address), conversation), address

    def _state_conversation(self, bound, cursor, project, conversation):
        if not isinstance(conversation, str) or _VIEW.fullmatch(conversation) is None:
            raise NotFound("conversation", conversation)
        # The host resolves actual own historic pairs or independently
        # authorized visible contacts for an empty pre-message view. It never
        # accepts a client-supplied actor or materializes a new public entity.
        address, peer = self._conversation_peer(bound, cursor, project, conversation)
        owner = ClientStateIdentity(bound.tenant_id, project,
                                    self._viewer_actor_ref(project, address), conversation)
        require_personal_owner(cursor, owner, self.project_service.context.principal_ref)
        return owner, address, peer

    def _state_visible_message(self, bound, cursor, project, conversation, reference):
        owner, address = self._state_actor(bound, cursor, project, conversation)
        try:
            message_id = parse_handle(reference, "message", project)
        except ValueError as error:
            raise InvalidToolArgument("through_message_handle", "Use a visible message in this conversation.") from error
        cursor.execute("SELECT c.sender,c.recipient,c.sequence FROM communication_messages c "
            "JOIN delivery_messages m USING(tenant_id,message_id) "
            "WHERE c.tenant_id=%s AND c.project_id=%s AND c.message_id=%s AND (c.sender=%s OR c.recipient=%s) "
            "AND m.packet_json->>'schema_version'='acs-message/1'",
            (bound.tenant_id, project, message_id, address, address))
        row = cursor.fetchone()
        if row is None or conversation_view_id(bound.tenant_id, project, row[0], row[1]) != conversation:
            raise NotFound("message", reference)
        require_personal_owner(cursor, owner, self.project_service.context.principal_ref)
        self._prepare_conversation_write(cursor, owner, address, row[1] if row[0] == address else row[0])
        # Public conversation_sequence is pair-local in both directions. The
        # global index sequence selects this committed prefix only and is never
        # stored as the caller's private frontier or returned to the client.
        cursor.execute("SELECT count(*) FROM communication_messages WHERE tenant_id=%s AND project_id=%s AND sequence<=%s "
            "AND ((sender=%s AND recipient=%s) OR (sender=%s AND recipient=%s))",
            (bound.tenant_id, project, row[2], row[0], row[1], row[1], row[0]))
        return owner, cursor.fetchone()[0]

    def read_state(self, project, conversation_id):
        def selected(bound, cursor, _root, _command):
            owner, _address, _peer = self._state_conversation(bound, cursor, project, conversation_id)
            return self._validate("ReadState", read_read_state(cursor, owner))
        return self._transaction(project, "read_message", selected)

    def update_read_state(self, project, conversation_id, body, *, expected_revision, client_request_id):
        body = self._validate("ReadStateWrite", body)

        def selected(bound, cursor, _root, _command):
            owner, sequence = self._state_visible_message(bound, cursor, project, conversation_id, body["through_message_handle"])
            address = self.project_service._communication_address(cursor, project)
            result = write_read_state(cursor, owner, through_message_handle=body["through_message_handle"],
                through_sequence=sequence, unread_override=body.get("unread_override"),
                expected_revision=expected_revision, client_request_id=self._private_request_key(project, address, "read_state", client_request_id))
            return self._validate("ReadState", result)
        return self._transaction(project, "read_message", selected)

    def preferences(self, project, conversation_id):
        def selected(bound, cursor, _root, _command):
            owner, _address, _peer = self._state_conversation(bound, cursor, project, conversation_id)
            return self._validate("Preferences", read_preferences(cursor, owner))
        return self._transaction(project, "read_message", selected)

    def update_preferences(self, project, conversation_id, body, *, expected_revision, client_request_id):
        body = self._validate("PreferencesWrite", body)

        def selected(bound, cursor, _root, _command):
            owner, address, _peer = self._state_conversation(bound, cursor, project, conversation_id)
            self._prepare_conversation_write(cursor, owner, address, _peer)
            result = write_preferences(cursor, owner, body, expected_revision=expected_revision,
                client_request_id=self._private_request_key(project, address, "preferences", client_request_id))
            return self._validate("Preferences", result)
        return self._transaction(project, "read_message", selected)

    def _state_draft_result(self, result):
        return self._validate("Draft", result)

    def draft(self, project, conversation_id):
        def selected(bound, cursor, _root, _command):
            owner, _address, _peer = self._state_conversation(bound, cursor, project, conversation_id)
            return self._state_draft_result(read_draft(cursor, owner))
        return self._transaction(project, "read_message", selected)

    def update_draft(self, project, conversation_id, body, *, expected_revision, client_request_id):
        body = self._validate("DraftWrite", body)

        def selected(bound, cursor, root, _command):
            owner, address, _peer = self._state_conversation(bound, cursor, project, conversation_id)
            if len(body["content"].encode("utf-8")) > MAX_DRAFT_BYTES:
                raise CommunicationHttpError("content_too_large", "Draft exceeds the 256 KiB UTF-8 byte limit.", status_code=413)
            def validate_attachments(cur, references):
                if not references:
                    return
                try:
                    limits = self._attachment_limits()
                    if len(set(references)) != len(references):
                        raise InvalidToolArgument("attachment_refs", "Use distinct attachment references.")
                    if len(references) > limits.attachments_per_message:
                        raise attachment_storage.AttachmentQuotaExceeded("draft attachment count budget exceeded")
                    uploader = self._attachment_owner(bound, cur, root, project)
                    # Freeze only the exact uploader's metadata. Drafts neither
                    # read CAS content nor pin/share the referenced uploads.
                    for reference in sorted(references):
                        attachment_storage.get_attachment(cur, uploader, reference, lock=True)
                    # Recheck every deadline after all potential row-lock waits,
                    # retaining the caller's original attachment order.
                    metadata = [attachment_storage.get_attachment(cur, uploader, reference) for reference in references]
                    for value in metadata:
                        if value["state"] == "expired":
                            raise attachment_storage.AttachmentExpired("draft upload expired")
                        if value["state"] not in {"reserved", "uploaded", "ready"}:
                            raise attachment_storage.AttachmentUploadConflict("draft upload is unavailable")
                    if (any(value["bytes"] > limits.file_bytes for value in metadata)
                            or sum(value["bytes"] for value in metadata) > limits.message_bytes):
                        raise attachment_storage.AttachmentQuotaExceeded("draft attachment byte budget exceeded")
                except Exception as error:
                    raise attachment_failure(error, read_only=True) from error
            return self._state_draft_result(write_draft(cursor, owner, body["content"], body["attachment_refs"],
                expected_revision=expected_revision, client_request_id=self._private_request_key(project, address, "draft.write", client_request_id),
                validate_attachments=validate_attachments))
        return self._transaction(project, "read_message", selected)

    def delete_draft(self, project, conversation_id, *, expected_revision, client_request_id):
        def selected(bound, cursor, _root, _command):
            owner, address, _peer = self._state_conversation(bound, cursor, project, conversation_id)
            return self._state_draft_result(delete_draft(cursor, owner,
                expected_revision=expected_revision, client_request_id=self._private_request_key(project, address, "draft.delete", client_request_id)))
        return self._transaction(project, "read_message", selected)
