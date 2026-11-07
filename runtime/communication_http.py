"""Authenticated HTTP v1 facade over the existing communication service.

The host supplies a trusted OAuth/request resolver. It must return the existing
ProjectService bound to that verified bearer, never a model-supplied identity or
a server-default credential. This module owns HTTP framing, not message storage,
send semantics, Native execution, or OAuth issuance.
"""
from __future__ import annotations

import hmac
import inspect
import json
import math
import re
import uuid
from dataclasses import dataclass
from functools import partial

import anyio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from runtime.errors import (
    AuthorizationDenied,
    IdempotencyConflict,
    InvalidToolArgument,
    NotFound,
    RevisionConflict,
    SchemaAdoptionError,
)
from runtime.project_service import ProjectService

PREFIX = "/api/communication/v1"
_BEARER = re.compile(r"Bearer ([A-Za-z0-9._~+/-]+=*)\Z", re.IGNORECASE)
_EFFECTS = frozenset({"none", "committed", "native_possible", "unknown"})


@dataclass(frozen=True)
class CommunicationHttpLimits:
    message_bytes: int = 256 * 1024
    json_bytes: int = 2 * 1024 * 1024
    page_items: int = 100
    inline_bytes: int = 65536
    attachment_count: int = 0
    attachment_bytes: int = 1
    attachment_total_bytes: int = 0
    attachment_staging_bytes: int = 0
    attachment_project_staging_bytes: int = 0
    attachment_staging_seconds: int = 0
    native_link_count: int = 0
    native_link_history_revisions: int = 0
    native_link_write_receipts: int = 0
    native_link_metadata_bytes: int = 0

    def __post_init__(self):
        for name, minimum, maximum in (("message_bytes", 1, 1024 * 1024),
            ("json_bytes", 1024, 8 * 1024 * 1024), ("page_items", 1, 100),
            ("inline_bytes", 1, 65536), ("attachment_count", 0, 8), ("attachment_bytes", 1, 256 * 1024 * 1024),
            ("attachment_total_bytes", 0, 1024**3), ("attachment_staging_bytes", 0, 8 * 1024**3),
            ("attachment_project_staging_bytes", 0, 64 * 1024**3), ("attachment_staging_seconds", 0, 7 * 86400),
            ("native_link_count", 0, 1000000), ("native_link_history_revisions", 0, 1000000),
            ("native_link_write_receipts", 0, 10000000), ("native_link_metadata_bytes", 0, 262144)):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError("invalid communication HTTP limit: " + name)


class CommunicationHttpError(Exception):
    """Commit-aware service failure; its public text must be implementation-owned."""

    def __init__(self, code, message, *, status_code=400, retryable=False, effect_state="none",
                 operation_ref=None, details=None, retry_after=None):
        if effect_state not in _EFFECTS:
            raise ValueError("invalid effect state")
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code
        self.retryable, self.effect_state = retryable, effect_state
        self.operation_ref, self.details, self.retry_after = operation_ref, details or {}, retry_after


def _default_service(projects, credential, *, message_bytes=262144):
    # The owning service is intentionally separate from HTTP and auth wiring.
    from runtime.communication_client_service import CommunicationClientService

    return CommunicationClientService(projects, credential, message_bytes=message_bytes)


def _contract(name, value):
    from runtime.client_contracts import ClientContracts

    return ClientContracts().validate(name, value)


def _query(request, allowed):
    values = {}
    for key, value in request.query_params.multi_items():
        if key not in allowed or key in values:
            raise CommunicationHttpError("invalid_argument", "Unknown or duplicate query parameter.")
        if not value or len(value) > (2048 if key == "cursor" else 1000 if key == "q" else 512):
            raise CommunicationHttpError("invalid_argument", "Invalid query parameter.")
        values[key] = value
    return values


def _integer(values, name, default, minimum, maximum):
    raw = values.pop(name, None)
    if raw is None:
        return default
    if not raw.isascii() or not raw.isdecimal():
        raise CommunicationHttpError("invalid_argument", "Invalid integer query parameter.")
    result = int(raw)
    if not minimum <= result <= maximum:
        raise CommunicationHttpError("invalid_argument", "Query parameter exceeds its limit.")
    return result


def _page(request, limits, extra=()):
    values = _query(request, {"cursor", "snapshot_id", "limit", *extra})
    values["limit"] = _integer(values, "limit", min(50, limits.page_items), 1, limits.page_items)
    values.setdefault("cursor", None)
    values.setdefault("snapshot_id", None)
    return values


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("non-finite JSON value")


async def _body(request, model, limits):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise CommunicationHttpError("invalid_argument", "An application/json request body is required.")
    lengths = request.headers.getlist("content-length")
    if len(lengths) > 1 or lengths and (not lengths[0].isascii() or not lengths[0].isdecimal()):
        raise CommunicationHttpError("invalid_argument", "Invalid Content-Length.")
    if lengths and int(lengths[0]) > limits.json_bytes:
        raise CommunicationHttpError("content_too_large", "Request exceeds the JSON byte limit.", status_code=413)
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > limits.json_bytes:
            raise CommunicationHttpError("content_too_large", "Request exceeds the JSON byte limit.", status_code=413)
        content.extend(chunk)
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=_object, parse_constant=_invalid_constant)
        if not isinstance(value, dict):
            raise TypeError("JSON object required")
        return _contract(model, value)
    except (UnicodeError, TypeError, ValueError, RecursionError) as error:
        raise CommunicationHttpError("invalid_argument", "Request does not match the communication contract.") from error


async def _run(method, *args, **kwargs):
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    value = await anyio.to_thread.run_sync(partial(method, *args, **kwargs))
    return await value if inspect.isawaitable(value) else value


def _refresh_interval(authorization):
    settings = getattr(getattr(authorization, "verifier", None), "settings", None)
    seconds = getattr(settings, "authorization_refresh_seconds", 1)
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
        raise TypeError("authorization refresh observation must be bounded")
    return max(0.05, min(0.5, seconds / 4))


async def _run_with_refresh(authorization, method, *args, **kwargs):
    """Keep a bounded auth observation alive without cancelling the command.

    A failed refresh invalidates the shared authorizer. The owning service's
    normal authorization points decide how to stop/observe its operation; this
    loop must not abandon, replay or abruptly cancel a possibly committed send.
    """
    refresh = getattr(authorization, "refresh", None)
    if not callable(refresh):
        return await _run(method, *args, **kwargs)
    interval = _refresh_interval(authorization)

    async def renew():
        while True:
            await anyio.sleep(interval)
            try:
                await _run(refresh)
            except Exception:  # noqa: BLE001 - failure is authority loss, never a command restart.
                authorization.valid = False
                return

    value, failure = None, None
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(renew)
        try:
            value = await _run(method, *args, **kwargs)
        except Exception as error:  # noqa: BLE001 - re-raise the original commit-aware failure outside TaskGroup.
            failure = error
        finally:
            tasks.cancel_scope.cancel()
    if failure is not None:
        raise failure
    return value


def _operation_ref(value):
    if isinstance(value, dict):
        for field in ("operation_ref", "operation_id"):
            if isinstance(value.get(field), str):
                return value[field]
    return None


def _write_preconditions(request):
    keys = request.headers.getlist("idempotency-key")
    if len(keys) != 1 or not 1 <= len(keys[0]) <= 200 or any(ord(char) < 32 or ord(char) == 127 for char in keys[0]):
        raise CommunicationHttpError("invalid_argument", "One stable Idempotency-Key is required.")
    versions = request.headers.getlist("if-match")
    matched = re.fullmatch(r'"(0|[1-9][0-9]{0,18})"', versions[0]) if len(versions) == 1 else None
    if matched is None or int(matched[1]) > 2**63 - 2:
        raise CommunicationHttpError("invalid_argument", "One quoted If-Match revision is required.")
    return {"expected_revision": int(matched[1]), "client_request_id": keys[0]}


def _problem(request, error):
    from runtime.project_http import OAuthScopeDenied

    effect = getattr(request.state, "effect_state", "none")
    operation_ref = getattr(request.state, "operation_ref", None)
    status, code, message, retryable, details, retry_after = 503, "receiver_unavailable", "Communication service is unavailable.", False, {}, None
    if isinstance(error, CommunicationHttpError):
        status, code, message, retryable = error.status_code, error.code, error.message, error.retryable
        effect, operation_ref, details, retry_after = error.effect_state, error.operation_ref or operation_ref, error.details, error.retry_after
    elif isinstance(error, OAuthScopeDenied):
        status, code, message = 403, "authorization_denied", "This action is not authorized."
    elif isinstance(error, PermissionError):
        status, code, message = 401, "unauthenticated", "Trusted bearer authentication is required."
    elif isinstance(error, AuthorizationDenied):
        status, code, message = 403, "authorization_denied", "This action is not authorized."
    elif isinstance(error, NotFound):
        status, code, message = 404, "not_found", "Resource not found or not visible."
    elif isinstance(error, (IdempotencyConflict, RevisionConflict)):
        status, code, message = 409, "idempotency_conflict" if isinstance(error, IdempotencyConflict) else "revision_conflict", "Request identity or version conflicts with the current state."
    elif isinstance(error, InvalidToolArgument):
        status, code, message = 400, "invalid_argument", "Invalid communication request."
        details = {"field": error.field}
    elif isinstance(error, SchemaAdoptionError):
        code, message = "schema_adoption_required", "Communication storage requires explicit adoption."
    elif getattr(error, "code", None) == "unsupported_projection":
        status, code, message = 409, "capability_unsupported", "This client projection is not available."
    public = {"code": code, "message": message, "retryable": bool(retryable), "effect_state": effect}
    if operation_ref:
        public["operation_ref"] = operation_ref
    if details:
        public["details"] = details
    headers = {"Cache-Control": "no-store"}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if status == 429:
        headers["Retry-After"] = str(retry_after if type(retry_after) is int and retry_after >= 0 else 1)
    return JSONResponse({"error": public, "request_id": request.state.request_id}, status_code=status, headers=headers)


def create_communication_app(project_provider, *, service_factory=None, limits=None, public_meta=None, event_limits=None):
    """Build the facade; binding the listener and verifying OAuth are host work.

    ``project_provider(Request)`` must return ``(ProjectService, bearer_token)``
    after actual transport authentication. Every protected route also checks the
    credential with that ProjectService. ``public_meta`` is an explicit trusted
    dictionary or zero-argument callback, never synthesized Authority identity.
    """
    if not callable(project_provider):
        raise TypeError("a trusted request-to-project resolver is required")
    limits = limits or CommunicationHttpLimits()
    if not isinstance(limits, CommunicationHttpLimits):
        raise TypeError("validated HTTP limits are required")
    factory = service_factory or partial(_default_service, message_bytes=limits.message_bytes)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(HTTPException)
    async def http_failure(request, error):
        code = {401: "unauthenticated", 403: "authorization_denied", 404: "not_found"}.get(error.status_code, "invalid_argument")
        response = _problem(request, CommunicationHttpError(code, "HTTP resource or method is unavailable.",
            status_code=error.status_code, effect_state=getattr(request.state, "effect_state", "none"),
            operation_ref=getattr(request.state, "operation_ref", None)))
        if error.status_code == 405 and error.headers and "Allow" in error.headers:
            response.headers["Allow"] = error.headers["Allow"]
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_failure(request, _error):
        return _problem(request, CommunicationHttpError("invalid_argument", "Invalid HTTP request."))

    @app.middleware("http")
    async def boundary(request, call_next):
        request.state.request_id = "http-" + uuid.uuid4().hex
        request.state.effect_state, request.state.operation_ref = "none", None
        try:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        except Exception as error:  # noqa: BLE001 - never expose tokens, DSNs or backend exception text.
            return _problem(request, error)

    async def service(request):
        headers = request.headers.getlist("authorization")
        matched = _BEARER.fullmatch(headers[0]) if len(headers) == 1 and len(headers[0]) <= 8199 else None
        if matched is None:
            raise PermissionError("bearer required")
        token = matched.group(1)
        resolved = await _run(project_provider, request)
        if not isinstance(resolved, tuple) or len(resolved) != 2:
            raise RuntimeError("trusted request resolver returned an invalid binding")
        projects, credential = resolved
        if not isinstance(projects, ProjectService) or not isinstance(credential, str):
            raise TypeError("trusted request resolver returned an invalid binding")
        if not hmac.compare_digest(token, credential):
            raise PermissionError("bearer binding differs")
        await _run(projects.service.authenticate, credential)
        request.state.project_service, request.state.credential = projects, credential
        if any(not isinstance(value, str) or not 1 <= len(value) <= 512
               or any(ord(char) < 32 or ord(char) == 127 for char in value)
               for value in request.path_params.values()):
            raise CommunicationHttpError("invalid_argument", "Invalid path reference.")
        return factory(projects, credential)

    async def result(request, instance, method_name, model, *args, mutating=False, success_status=None, transactional=False, **kwargs):
        method = getattr(instance, method_name, None)
        if not callable(method):
            raise CommunicationHttpError("capability_unsupported", "This communication feature is not available.", status_code=409)
        projects = getattr(request.state, "project_service", None) or getattr(instance, "project_service", None)
        credential = getattr(request.state, "credential", None)
        authorization = getattr(projects, "token_authorization", None)
        refresh = getattr(authorization, "refresh", None)
        if callable(refresh):
            try:
                await _run(refresh)
            except Exception:
                authorization.valid = False
                raise
        if projects is not None:
            await _run(projects.service.authenticate, credential)
        if mutating:
            request.state.effect_state = "unknown"
        try:
            value = await _run_with_refresh(authorization, method, *args, **kwargs)
        except (RevisionConflict, IdempotencyConflict, NotFound, InvalidToolArgument, AuthorizationDenied, PermissionError):
            # These private-state methods authorize and validate before their
            # transaction commits. A rejected CAS/key/identity has no effect.
            if transactional:
                request.state.effect_state = "none"
            raise
        if mutating:
            request.state.effect_state = "committed"
            request.state.operation_ref = _operation_ref(value)
        if projects is not None:
            await _run(projects.service.authenticate, credential)
        complete = getattr(value, "require_complete", None)
        if callable(complete):
            value = complete()
        validated = _contract(model, value)
        status = 200 if not mutating or validated.get("duplicate") is True else 201
        return JSONResponse(validated, status_code=success_status or status)

    @app.get(PREFIX + "/meta")
    async def meta(request: Request):
        _query(request, set())
        if public_meta is None:
            raise CommunicationHttpError("receiver_unavailable", "Public communication metadata is not configured.", status_code=503)
        value = await _run(public_meta) if callable(public_meta) else public_meta
        value = _contract("Meta", value)
        advertised = value["limits"]
        if any(advertised[field] != getattr(limits, field) for field in (
                "message_bytes", "page_items", "attachment_count", "attachment_bytes", "attachment_total_bytes",
                "attachment_staging_bytes", "attachment_project_staging_bytes", "attachment_staging_seconds",
                "native_link_count", "native_link_history_revisions", "native_link_write_receipts", "native_link_metadata_bytes")):
            raise RuntimeError("advertised communication limits differ from enforced limits")
        return JSONResponse(value)

    @app.get(PREFIX + "/profile")
    async def profile(request: Request):
        instance = await service(request)
        _query(request, set())
        return await result(request, instance, "profile", "Actor")

    @app.get(PREFIX + "/projects")
    async def projects(request: Request):
        instance = await service(request)
        return await result(request, instance, "projects", "ProjectPage", **_page(request, limits))

    @app.get(PREFIX + "/projects/{project_id}/routes")
    async def routes(project_id: str, request: Request):
        instance = await service(request)
        return await result(request, instance, "routes", "RoutePage", project_id, **_page(request, limits))

    @app.get(PREFIX + "/projects/{project_id}/contacts")
    async def contacts(project_id: str, request: Request):
        instance = await service(request)
        return await result(request, instance, "contacts", "ContactPage", project_id,
                            **_page(request, limits, {"name", "scope_handle"}))

    @app.get(PREFIX + "/projects/{project_id}/messages")
    async def messages(project_id: str, request: Request):
        instance = await service(request)
        params = _page(request, limits, {"with", "conversation_id", "reply_root", "direction"})
        if params.get("direction", "both") not in {"both", "incoming", "outgoing"}:
            raise CommunicationHttpError("invalid_argument", "Invalid message direction.")
        return await result(request, instance, "messages", "MessagePage", project_id, **params)

    @app.get(PREFIX + "/projects/{project_id}/search")
    async def search(project_id: str, request: Request):
        instance = await service(request)
        params = _page(request, limits, {"q", "with", "conversation_id"})
        if "q" not in params:
            raise CommunicationHttpError("invalid_argument", "A search query is required.")
        return await result(request, instance, "search", "SearchHitPage", project_id, **params)

    @app.get(PREFIX + "/projects/{project_id}/snapshot")
    async def snapshot(project_id: str, request: Request):
        instance = await service(request)
        params = _query(request, {"limit"})
        limit = _integer(params, "limit", 50, 1, limits.page_items)
        return await result(request, instance, "snapshot", "Snapshot", project_id, limit=limit)

    @app.get(PREFIX + "/projects/{project_id}/receivers")
    async def receivers(project_id: str, request: Request):
        instance = await service(request)
        return await result(request, instance, "receivers", "ReceiverPage", project_id, **_page(request, limits))

    @app.post(PREFIX + "/projects/{project_id}/receivers/{receiver_id:path}/actions")
    async def recover_receiver(project_id: str, receiver_id: str, request: Request):
        instance = await service(request)
        _query(request, set())
        keys = request.headers.getlist("idempotency-key")
        if len(keys) != 1 or not 1 <= len(keys[0]) <= 200 or any(ord(char) < 32 or ord(char) == 127 for char in keys[0]):
            raise CommunicationHttpError("invalid_argument", "One stable Idempotency-Key is required.")
        if request.headers.getlist("if-match"):
            raise CommunicationHttpError("invalid_argument", "Recovery revision belongs in expected_revision.")
        body = await _body(request, "RecoveryRequest", limits)
        return await result(request, instance, "recover_receiver", "Operation", project_id, receiver_id, body,
            client_request_id=keys[0], mutating=True, transactional=True, success_status=202)

    @app.get(PREFIX + "/projects/{project_id}/receivers/{receiver_id:path}")
    async def receiver(project_id: str, receiver_id: str, request: Request):
        instance = await service(request)
        _query(request, set())
        return await result(request, instance, "receiver", "Receiver", project_id, receiver_id)

    @app.get(PREFIX + "/projects/{project_id}/notices")
    async def notices(project_id: str, request: Request):
        instance = await service(request)
        return await result(request, instance, "notices", "NoticePage", project_id, **_page(request, limits))

    @app.put(PREFIX + "/projects/{project_id}/notices/{notice_handle}/seen")
    async def notice_seen(project_id: str, notice_handle: str, request: Request):
        instance = await service(request)
        _query(request, set())
        conditions = _write_preconditions(request)
        body = await _body(request, "SeenWrite", limits)
        return await result(request, instance, "mark_notice_seen", "Notice", project_id, notice_handle, body,
                            mutating=True, success_status=200, transactional=True, **conditions)

    @app.get(PREFIX + "/projects/{project_id}/native-links")
    async def native_links(project_id: str, request: Request):
        instance = await service(request)
        return await result(request, instance, "native_links", "NativeLinkPage", project_id,
                            **_page(request, limits, {"address"}))

    @app.put(PREFIX + "/projects/{project_id}/native-links/{link_id}")
    async def native_link_write(project_id: str, link_id: str, request: Request):
        instance = await service(request)
        _query(request, set())
        keys = request.headers.getlist("idempotency-key")
        if len(keys) != 1 or not 1 <= len(keys[0]) <= 200 or any(ord(char) < 32 or ord(char) == 127 for char in keys[0]):
            raise CommunicationHttpError("invalid_argument", "One stable Idempotency-Key is required.")
        body = await _body(request, "NativeLinkWrite", limits)
        return await result(request, instance, "write_native_link", "NativeLink", project_id, link_id, body,
                            client_request_id=keys[0], mutating=True, success_status=200, transactional=True)

    @app.get(PREFIX + "/projects/{project_id}/conversations")
    async def conversations(project_id: str, request: Request):
        instance = await service(request)
        params = _page(request, limits, {"include_archived"})
        archived = params.pop("include_archived", "false")
        if archived not in {"true", "false"}:
            raise CommunicationHttpError("invalid_argument", "include_archived must be true or false.")
        return await result(request, instance, "conversations", "ConversationPage", project_id,
                            include_archived=archived == "true", **params)

    @app.get(PREFIX + "/projects/{project_id}/conversations/resolve")
    async def resolve_conversation(project_id: str, request: Request):
        instance = await service(request)
        params = _query(request, {"with"})
        if "with" not in params:
            raise CommunicationHttpError("invalid_argument", "A visible peer address is required.")
        return await result(request, instance, "resolve_conversation", "Conversation", project_id, peer=params["with"])

    @app.get(PREFIX + "/projects/{project_id}/conversations/{conversation_id}")
    async def conversation(project_id: str, conversation_id: str, request: Request):
        instance = await service(request)
        _query(request, set())
        return await result(request, instance, "conversation", "Conversation", project_id, conversation_id)

    # All personal resources use separate versions and keys; none consumes a
    # message or changes the other participant's view.
    for resource, read_method, write_method, model, write_model in (
        ("read-state", "read_state", "update_read_state", "ReadState", "ReadStateWrite"),
        ("preferences", "preferences", "update_preferences", "Preferences", "PreferencesWrite"),
        ("draft", "draft", "update_draft", "Draft", "DraftWrite"),
    ):
        def resource_routes(resource, read_method, write_method, model, write_model):
            async def read_personal(project_id: str, conversation_id: str, request: Request):
                instance = await service(request)
                _query(request, set())
                return await result(request, instance, read_method, model, project_id, conversation_id)

            async def write_personal(project_id: str, conversation_id: str, request: Request):
                instance = await service(request)
                _query(request, set())
                conditions = _write_preconditions(request)
                body = await _body(request, write_model, limits)
                return await result(request, instance, write_method, model, project_id, conversation_id, body,
                                    mutating=True, success_status=200, transactional=True, **conditions)

            path = PREFIX + "/projects/{project_id}/conversations/{conversation_id}/" + resource
            app.add_api_route(path, read_personal, methods=["GET"], name=read_method)
            app.add_api_route(path, write_personal, methods=["PUT"], name=write_method)

        resource_routes(resource, read_method, write_method, model, write_model)

    @app.delete(PREFIX + "/projects/{project_id}/conversations/{conversation_id}/draft")
    async def delete_draft(project_id: str, conversation_id: str, request: Request):
        instance = await service(request)
        _query(request, set())
        return await result(request, instance, "delete_draft", "Draft", project_id, conversation_id,
                            mutating=True, success_status=200, transactional=True, **_write_preconditions(request))

    # Register the longer static suffix first; no resource lookup grants access.
    @app.get(PREFIX + "/projects/{project_id}/messages/{message_handle}/delivery")
    async def delivery(project_id: str, message_handle: str, request: Request):
        instance = await service(request)
        _query(request, set())
        return await result(request, instance, "delivery", "DeliveryFacts", project_id, message_handle)

    @app.get(PREFIX + "/projects/{project_id}/messages/{message_handle}")
    async def read_message(project_id: str, message_handle: str, request: Request):
        instance = await service(request)
        params = _query(request, {"offset", "max_inline_bytes", "include_native_source"})
        include = params.get("include_native_source", "false")
        if include not in {"true", "false"}:
            raise CommunicationHttpError("invalid_argument", "Use a boolean Native source selection")
        offset = _integer(params, "offset", 0, 0, 2**63 - 1)
        maximum = _integer(params, "max_inline_bytes", min(16384, limits.inline_bytes), 1, limits.inline_bytes)
        return await result(request, instance, "read_message", "ReadMessageResponse", project_id, message_handle,
                            offset=offset, max_inline_bytes=maximum,
                            **({"include_native_source": True} if include == "true" else {}))

    @app.post(PREFIX + "/projects/{project_id}/waits")
    async def wait(project_id: str, request: Request):
        instance = await service(request)
        _query(request, set())
        body = await _body(request, "WaitRequest", limits)
        return await result(request, instance, "wait", "WaitResponse", project_id, body)

    @app.get(PREFIX + "/projects/{project_id}/operations/{operation_id}")
    async def operation(project_id: str, operation_id: str, request: Request):
        instance = await service(request)
        _query(request, set())
        return await result(request, instance, "operation", "Operation", operation_id, project_id=project_id)

    @app.post(PREFIX + "/projects/{project_id}/messages")
    async def send(project_id: str, request: Request):
        instance = await service(request)
        _query(request, set())
        keys = request.headers.getlist("idempotency-key")
        if len(keys) != 1 or not 1 <= len(keys[0]) <= 200 or any(ord(char) < 32 or ord(char) == 127 for char in keys[0]):
            raise CommunicationHttpError("invalid_argument", "One stable Idempotency-Key is required.")
        body = await _body(request, "SendRequest", limits)
        if not body["content"].strip():
            raise CommunicationHttpError("invalid_argument", "Provide nonempty message text.")
        try:
            size = len(body["content"].encode("utf-8"))
        except UnicodeError as error:
            raise CommunicationHttpError("invalid_argument", "Message text must be valid UTF-8.") from error
        if size > limits.message_bytes:
            raise CommunicationHttpError("content_too_large", "Message exceeds the advertised UTF-8 limit.", status_code=413)
        if len(body.get("attachment_refs", [])) > limits.attachment_count:
            raise CommunicationHttpError("capability_unsupported", "Message attachments are not available under these limits.", status_code=409)
        return await result(request, instance, "send", "SendResponse", project_id, body,
                            client_request_id=keys[0], mutating=True)

    from runtime.communication_event_http import register_event_routes

    register_event_routes(app, service=service, run=_run, run_with_refresh=_run_with_refresh, contract=_contract, limits=event_limits)
    from runtime.communication_attachment_http import register_attachment_routes

    register_attachment_routes(app, service=service, result=result, run=_run, run_with_refresh=_run_with_refresh,
        contract=_contract, body_reader=_body, query=_query, limits=limits)
    return app
