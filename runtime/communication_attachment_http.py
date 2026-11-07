"""Bounded attachment HTTP framing over the supplied authenticated facade.

Every upload facade callback owns a short transaction; incoming streaming and
CAS work never share a request-wide SQL transaction. This router creates no
OAuth identity, local path, artifact reader or Native operation.
"""
from __future__ import annotations

import hashlib
import re

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from runtime.communication_http import PREFIX, CommunicationHttpError


def _invalid(message="Invalid attachment HTTP request."):
    return CommunicationHttpError("invalid_argument", message)


def _key(request):
    keys = request.headers.getlist("idempotency-key")
    if len(keys) != 1 or not 1 <= len(keys[0]) <= 200 or any(ord(character) < 32 or ord(character) == 127 for character in keys[0]):
        raise _invalid("One stable Idempotency-Key is required.")
    return keys[0]


def _path(request):
    if any(type(value) is not str or not 1 <= len(value) <= 512 or any(ord(character) < 32 or ord(character) == 127 for character in value)
           for value in request.path_params.values()):
        raise _invalid("Invalid attachment path reference.")


def _enabled(limits):
    maximum = getattr(limits, "attachment_bytes", 0)
    if type(maximum) is not int or maximum < 0:
        raise TypeError("validated attachment byte limit is required")
    if not maximum:
        raise CommunicationHttpError("capability_unsupported", "Attachments are not enabled.", status_code=409)
    return maximum


def _upload_headers(request, maximum):
    for header in ("content-range", "range", "if-range", "content-encoding", "upload-offset", "upload-length", "upload-concat", "tus-resumable"):
        if request.headers.getlist(header):
            raise _invalid("Only an unencoded full-file upload is supported.")
    types = request.headers.getlist("content-type")
    if len(types) != 1 or types[0].strip().lower() != "application/octet-stream":
        raise _invalid("Upload content as application/octet-stream.")
    lengths = request.headers.getlist("content-length")
    if len(lengths) > 1 or lengths and (not lengths[0].isascii() or not lengths[0].isdecimal()):
        raise _invalid("Use one numeric Content-Length.")
    if lengths and request.headers.getlist("transfer-encoding"):
        raise _invalid("Content-Length and Transfer-Encoding cannot be combined.")
    length = int(lengths[0]) if lengths else None
    if length is not None and length > maximum:
        raise CommunicationHttpError("content_too_large", "Attachment exceeds the upload byte limit.", status_code=413)
    return length


def _committed_error(error, request):
    if isinstance(error, CommunicationHttpError) and error.effect_state == "none" and getattr(request.state, "effect_state", "none") == "committed":
        return CommunicationHttpError(error.code, error.message, status_code=error.status_code, retryable=error.retryable,
            effect_state="committed", operation_ref=error.operation_ref, details=error.details, retry_after=error.retry_after)
    return error


def register_attachment_routes(app, *, service, result, run, run_with_refresh, contract, body_reader, query, limits):
    async def refresh(request):
        projects = request.state.project_service
        authorization = getattr(projects, "token_authorization", None)
        renew = getattr(authorization, "refresh", None)
        if callable(renew):
            try:
                await run(renew)
            except Exception:
                authorization.valid = False
                raise
        await run(projects.service.authenticate, request.state.credential)
        return authorization

    async def invoke(request, instance, name, *args, **kwargs):
        method = getattr(instance, name, None)
        if not callable(method):
            raise CommunicationHttpError("capability_unsupported", "This attachment operation is unavailable.", status_code=409)
        authorization = await refresh(request)
        return await run_with_refresh(authorization, method, *args, **kwargs)

    @app.post(PREFIX + "/projects/{project_id}/attachments")
    async def create(project_id: str, request: Request):
        instance = await service(request)
        _path(request)
        query(request, set())
        _enabled(limits)
        key = _key(request)
        body = await body_reader(request, "AttachmentCreate", limits)
        return await result(request, instance, "create_attachment", "Attachment", project_id, body,
            client_request_id=key, mutating=True, success_status=201, transactional=True)

    @app.get(PREFIX + "/projects/{project_id}/attachments/{attachment_id}")
    async def metadata(project_id: str, attachment_id: str, request: Request):
        instance = await service(request)
        _path(request)
        query(request, set())
        _enabled(limits)
        return await result(request, instance, "attachment", "Attachment", project_id, attachment_id, success_status=200)

    @app.put(PREFIX + "/projects/{project_id}/attachments/{attachment_id}/content")
    async def upload(project_id: str, attachment_id: str, request: Request):
        instance = await service(request)
        _path(request)
        query(request, set())
        maximum, key = _enabled(limits), _key(request)
        content_length = _upload_headers(request, maximum)
        try:
            context = await invoke(request, instance, "begin_attachment_upload", project_id, attachment_id,
                                   content_type="application/octet-stream", client_request_id=key)
            request.state.effect_state = "committed"
            declaration = contract("Attachment", context.attachment)
            declared = declaration["bytes"]
            if type(context.lease.chunk_bytes) is not int or not 1 <= context.lease.chunk_bytes <= 1024 * 1024:
                raise RuntimeError("invalid captured attachment chunk bound")
            if type(context.lease.revision) is not int or context.lease.revision < 1 or not 1 <= declared <= maximum:
                raise RuntimeError("invalid captured attachment reservation")
            if content_length is not None and content_length != declared:
                raise CommunicationHttpError("invalid_argument", "Content-Length differs from the attachment reservation.")
            observed, offset, last_revision = 0, 0, context.lease.revision
            checksum, pending = hashlib.sha256(), bytearray()
            async for data in request.stream():
                if not data:
                    continue
                observed += len(data)
                if observed > maximum or observed > declared:
                    raise CommunicationHttpError("content_too_large", "Upload exceeds its declared byte limit.", status_code=413)
                checksum.update(data)
                if context.prior_result is not None:
                    continue  # Still verify the complete duplicate body, never reupload.
                view, position = memoryview(data), 0
                while position < len(view):
                    wanted = min(context.lease.chunk_bytes, declared - offset)
                    amount = min(wanted - len(pending), len(view) - position)
                    pending.extend(view[position:position + amount])
                    position += amount
                    if len(pending) == wanted:
                        chunk = bytes(pending)
                        pending.clear()
                        receipt = await invoke(request, instance, "append_attachment_upload", context, offset, chunk)
                        if receipt is not None:
                            if type(receipt) is not dict or type(receipt.get("revision")) is not int or receipt["revision"] < last_revision:
                                raise RuntimeError("invalid attachment append receipt")
                            last_revision = receipt["revision"]
                        offset += len(chunk)
                        del chunk
            # A short EOF is delegated with actual size/hash and the last real
            # append revision. No fabricated padding or partial chunk is stored.
            value = await invoke(request, instance, "complete_attachment_upload", context,
                observed_bytes=observed, observed_sha256=checksum.hexdigest(), last_revision=last_revision)
            await refresh(request)
            return JSONResponse(contract("Attachment", value), status_code=200, headers={"Cache-Control": "no-store"})
        except Exception as error:
            adjusted = _committed_error(error, request)
            if adjusted is error:
                raise
            raise adjusted from error

    @app.post(PREFIX + "/projects/{project_id}/attachments/{attachment_id}/finalize")
    async def finalize(project_id: str, attachment_id: str, request: Request):
        instance = await service(request)
        _path(request)
        query(request, set())
        _enabled(limits)
        key = _key(request)
        body = await body_reader(request, "AttachmentFinalize", limits)
        return await result(request, instance, "finalize_attachment", "Attachment", project_id, attachment_id, body,
            client_request_id=key, mutating=True, success_status=200)

    @app.get(PREFIX + "/projects/{project_id}/attachments/{attachment_id}/content")
    async def download(project_id: str, attachment_id: str, request: Request):
        instance = await service(request)
        _path(request)
        query(request, set())
        _enabled(limits)
        if request.headers.getlist("range") or request.headers.getlist("if-range"):
            raise _invalid("Partial attachment downloads are not supported.")
        value = await invoke(request, instance, "download_attachment", project_id, attachment_id)
        await refresh(request)
        if (type(value.data) is not bytes or type(value.sha256) is not str or re.fullmatch(r"[a-f0-9]{64}", value.sha256) is None
                or hashlib.sha256(value.data).hexdigest() != value.sha256 or type(value.media_type) is not str
                or not 1 <= len(value.media_type) <= 256 or type(value.content_disposition) is not str
                or any(ord(character) < 32 or ord(character) == 127 for character in value.media_type + value.content_disposition)):
            raise CommunicationHttpError("attachment_content_unavailable", "Verified attachment content is unavailable.", status_code=503)
        return Response(value.data, status_code=200, headers={"Content-Type": value.media_type,
            "Content-Disposition": value.content_disposition, "Content-Length": str(len(value.data)),
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Accept-Ranges": "none", "ETag": '"' + value.sha256 + '"'})
