"""Synthetic facade + real attachment router/ASGI framing; no database or CAS.

Content bytes and acknowledgments are controlled fixtures. Actual Scope CAS,
MIME validation, ACL and upload transaction behavior have independent PG tests.
"""
from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from runtime.communication_attachment_http import register_attachment_routes
from runtime.communication_http import (
    PREFIX,
    CommunicationHttpError,
    _body,
    _contract,
    _problem,
    _query,
    _run,
    _run_with_refresh,
)

TOKEN = "synthetic-attachment-token"
ID = "attachment-" + "a" * 32
DATA = b"abcdefghij"
BASE = "/projects/p/attachments"


def metadata(state="reserved", revision=1):
    return {"attachment_id": ID, "project_id": "p", "name": "fixture.png", "media_type": "image/png",
        "bytes": len(DATA), "sha256": hashlib.sha256(DATA).hexdigest(), "state": state,
        "upload_path": None, "expires_at": "2030-01-01T00:00:00Z", "revision": revision}


class FakeFacade:
    def __init__(self, state):
        self.state = state
        self.calls, self.chunks = [], []
        self.prior_result = None
        self.append_failure = self.complete_failure = None
        self.invalid_complete = self.revoke_complete = self.revoke_download = False
        self.corrupt_download = False

    def create_attachment(self, project, body, *, client_request_id):
        self.calls.append(("create", project, deepcopy(body), client_request_id))
        return metadata()

    def attachment(self, project, identifier):
        self.calls.append(("metadata", project, identifier))
        return metadata()

    def begin_attachment_upload(self, project, identifier, *, content_type, client_request_id):
        self.calls.append(("begin", project, identifier, content_type, client_request_id))
        return SimpleNamespace(project=project, attachment_id=identifier, owner="synthetic-viewer",
            lease=SimpleNamespace(chunk_bytes=4, revision=2), attachment=metadata(), namespace="synthetic-plan", content_type=content_type,
            prior_result=deepcopy(self.prior_result))

    def append_attachment_upload(self, context, offset, data):
        self.calls.append(("append", offset, len(data)))
        if self.append_failure is not None:
            raise self.append_failure
        self.chunks.append((offset, data))
        return {"revision": 2 + len(self.chunks), "next_offset": offset + len(data)}

    def complete_attachment_upload(self, context, *, observed_bytes, observed_sha256, last_revision):
        self.calls.append(("complete", observed_bytes, observed_sha256, last_revision))
        if self.complete_failure is not None:
            raise self.complete_failure
        if (observed_bytes, observed_sha256) != (len(DATA), hashlib.sha256(DATA).hexdigest()):
            raise CommunicationHttpError("idempotency_conflict" if context.prior_result else "invalid_argument",
                "Controlled observed upload mismatch.", status_code=409 if context.prior_result else 400)
        if self.revoke_complete:
            self.state.authorized = False
        if self.invalid_complete:
            return {"private_data": "must not leak"}
        return deepcopy(context.prior_result) if context.prior_result else metadata("uploaded", last_revision + 1)

    def finalize_attachment(self, project, identifier, body, *, client_request_id):
        self.calls.append(("finalize", project, identifier, deepcopy(body), client_request_id))
        return metadata("ready", 7)

    def download_attachment(self, project, identifier):
        self.calls.append(("download", project, identifier))
        if self.revoke_download:
            self.state.authorized = False
        return SimpleNamespace(data=DATA, media_type="image/png", content_disposition='attachment; filename="fixture.png"',
            sha256="0" * 64 if self.corrupt_download else hashlib.sha256(DATA).hexdigest())


@pytest.fixture
def boundary():
    state = SimpleNamespace(authorized=True, auth_calls=0, refresh_calls=0, result_calls=[],
                            limits=SimpleNamespace(attachment_bytes=12, json_bytes=4096))
    facade = FakeFacade(state)
    state.facade = facade

    class Authorization:
        valid = True
        verifier = SimpleNamespace(settings=SimpleNamespace(authorization_refresh_seconds=1))

        async def refresh(self):
            state.refresh_calls += 1
            if not state.authorized:
                raise PermissionError("synthetic auth observation revoked")

    def authenticate(credential):
        state.auth_calls += 1
        if not state.authorized or credential != TOKEN:
            raise PermissionError("synthetic credential rejected")

    projects = SimpleNamespace(service=SimpleNamespace(authenticate=authenticate), token_authorization=Authorization())

    async def service(request):
        if request.headers.getlist("authorization") != ["Bearer " + TOKEN]:
            raise PermissionError("trusted authentication required before framing")
        authenticate(TOKEN)
        request.state.project_service, request.state.credential = projects, TOKEN
        return facade

    async def result(request, instance, method, model, *args, mutating=False, success_status=None, **kwargs):
        kwargs.pop("transactional", None)
        state.result_calls.append((method, mutating, success_status))
        await _run(projects.token_authorization.refresh)
        authenticate(TOKEN)
        if mutating:
            request.state.effect_state = "unknown"
        value = await _run_with_refresh(projects.token_authorization, getattr(instance, method), *args, **kwargs)
        if mutating:
            request.state.effect_state = "committed"
        authenticate(TOKEN)
        return JSONResponse(_contract(model, value), status_code=success_status or 200)

    app = FastAPI()

    @app.middleware("http")
    async def errors(request, call_next):
        request.state.effect_state, request.state.operation_ref, request.state.request_id = "none", None, "synthetic-request"
        try:
            return await call_next(request)
        except Exception as error:  # noqa: BLE001 - exercise the real redacted error boundary.
            return _problem(request, error)

    register_attachment_routes(app, service=service, result=result, run=_run, run_with_refresh=_run_with_refresh,
        contract=_contract, body_reader=_body, query=_query, limits=state.limits)
    state.app, state.projects = app, projects
    return state


def request(f, method, suffix="", *, authenticated=True, **kwargs):
    async def exercise():
        headers = [("Authorization", "Bearer " + TOKEN)] if authenticated else []
        extra = kwargs.pop("headers", {})
        headers.extend(extra.items() if isinstance(extra, dict) else extra)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f.app), base_url="http://attachment.synthetic") as client:
            return await client.request(method, PREFIX + BASE + suffix, headers=headers, **kwargs)
    return asyncio.run(exercise())


def put(f, *, content=DATA, headers=None, authenticated=True):
    current = {"Content-Type": "application/octet-stream", "Idempotency-Key": "stable-upload"}
    current.update(headers or {})
    return request(f, "PUT", "/" + ID + "/content", headers=current, content=content, authenticated=authenticated)


def fragments(*parts):
    async def generate():
        for part in parts:
            yield part
    return generate()


def test_json_methods_use_contracts_fixed_status_and_require_no_if_match(boundary):
    f = boundary
    body = {key: metadata()[key] for key in ("name", "media_type", "bytes", "sha256")}
    created = request(f, "POST", headers={"Idempotency-Key": "reserve-key"}, json=body)
    assert created.status_code == 201
    assert request(f, "GET", "/" + ID).status_code == 200
    final = request(f, "POST", "/" + ID + "/finalize", headers={"Idempotency-Key": "finalize-key"},
                    json={key: body[key] for key in ("sha256", "bytes")})
    assert final.status_code == 200 and final.json()["state"] == "ready"
    assert f.result_calls == [("create_attachment", True, 201), ("attachment", False, 200), ("finalize_attachment", True, 200)]


def test_fragmented_full_upload_uses_captured_deterministic_chunk_bound_and_last_revision(boundary):
    f = boundary
    response = put(f, content=fragments(b"a", b"bc", b"de", b"fghij"))
    assert response.status_code == 200 and response.json()["state"] == "uploaded"
    assert f.facade.chunks == [(0, b"abcd"), (4, b"efgh"), (8, b"ij")]
    assert f.facade.calls[-1] == ("complete", 10, hashlib.sha256(DATA).hexdigest(), 5)
    assert f.refresh_calls >= len(f.facade.calls) + 1
    assert f.auth_calls >= len(f.facade.calls) + 2
    assert f.facade.calls[0][3] == "application/octet-stream"  # Reserved MIME remains image/png.


@pytest.mark.parametrize("headers", [
    {"Content-Range": "bytes 0-9/10"}, {"Content-Encoding": "gzip"}, {"Range": "bytes=0-9"},
    {"If-Range": '"old"'}, {"Upload-Offset": "0"}, {"Tus-Resumable": "1.0.0"},
    {"Content-Type": "image/png"}, {"Content-Length": "-1"}, {"Content-Length": "1.0"},
    {"Content-Length": "garbage"}, {"Content-Length": "13"},
])
def test_invalid_binary_framing_and_oversized_length_fail_before_begin(boundary, headers):
    response = put(boundary, headers=headers)
    assert response.status_code in {400, 413}
    assert response.json()["error"]["effect_state"] == "none" and boundary.facade.calls == []


def test_duplicate_content_length_and_key_are_rejected_without_begin(boundary):
    for duplicated in ([("Content-Length", "10"), ("Content-Length", "10")],
                       [("Idempotency-Key", "a"), ("Idempotency-Key", "b")]):
        headers = [("Content-Type", "application/octet-stream")]
        if duplicated[0][0] != "Idempotency-Key":
            headers.append(("Idempotency-Key", "stable"))
        headers.extend(duplicated)
        response = request(boundary, "PUT", "/" + ID + "/content", headers=headers, content=DATA)
        assert response.status_code == 400 and boundary.facade.calls == []


@pytest.mark.parametrize("key", [None, "", "x" * 201, "bad\x7fkey"])
def test_every_mutation_requires_one_opaque_idempotency_key(boundary, key):
    headers = {"Content-Type": "application/octet-stream"}
    if key is not None:
        headers["Idempotency-Key"] = key
    response = request(boundary, "PUT", "/" + ID + "/content", headers=headers, content=DATA)
    assert response.status_code == 400 and boundary.facade.calls == []


def test_authentication_precedes_invalid_headers_query_id_and_any_body_consumption(boundary):
    consumed = []

    async def never_read():
        consumed.append(True)
        yield b"private bytes"

    response = request(boundary, "PUT", "/%00/content?sender=forged", authenticated=False,
                       headers={"Content-Type": "wrong", "Content-Length": "invalid"}, content=never_read())
    assert response.status_code == 401 and consumed == [] and boundary.facade.calls == []


def test_declared_length_mismatch_after_plan_preserves_committed_effect(boundary):
    response = put(boundary, content=b"short")
    assert response.status_code == 400 and response.json()["error"]["effect_state"] == "committed"
    assert [call[0] for call in boundary.facade.calls] == ["begin"]


def test_stream_overrun_is_rejected_before_buffering_or_appending_big_frame(boundary):
    response = put(boundary, content=fragments(b"abcd", b"e" * 20))
    assert response.status_code == 413 and response.json()["error"]["effect_state"] == "committed"
    assert boundary.facade.chunks == [(0, b"abcd")]
    assert not any(call[0] == "complete" for call in boundary.facade.calls)


@pytest.mark.parametrize("data", [b"", b"abcde", b"xxxxxxxxxx"])
def test_short_eof_and_digest_mismatch_delegate_actual_observation_for_atomic_rejection(boundary, data):
    response = put(boundary, content=fragments(data))
    assert response.status_code == 400 and response.json()["error"]["effect_state"] == "committed"
    completion = boundary.facade.calls[-1]
    assert completion[:3] == ("complete", len(data), hashlib.sha256(data).hexdigest())
    assert all(chunk for _offset, chunk in boundary.facade.chunks)
    assert sum(len(chunk) for _offset, chunk in boundary.facade.chunks) <= len(data)


def test_duplicate_completed_upload_still_hashes_body_without_any_append(boundary):
    boundary.facade.prior_result = metadata("uploaded", 6)
    first = put(boundary, content=fragments(b"abc", b"defghij"))
    assert first.status_code == 200 and first.json() == boundary.facade.prior_result
    assert boundary.facade.chunks == [] and not any(call[0] == "append" for call in boundary.facade.calls)
    changed = put(boundary, content=fragments(b"xxxxxxxxxx"))
    assert changed.status_code == 409 and changed.json()["error"]["effect_state"] == "committed"
    assert boundary.facade.calls[-1][1:3] == (10, hashlib.sha256(b"xxxxxxxxxx").hexdigest())


def test_disconnect_retains_partial_upload_and_never_restarts_or_completes_it(boundary):
    async def disconnect():
        yield b"abcd"
        raise httpx.ReadError("controlled client disconnect")

    response = put(boundary, content=disconnect())
    assert response.status_code == 503 and response.json()["error"]["effect_state"] == "committed"
    assert boundary.facade.chunks == [(0, b"abcd")]
    assert [call[0] for call in boundary.facade.calls] == ["begin", "append"]
    assert "controlled client disconnect" not in response.text


@pytest.mark.parametrize("phase", ["append", "complete", "schema", "final_auth"])
def test_post_begin_failures_never_claim_no_effect(boundary, phase):
    if phase == "append":
        boundary.facade.append_failure = CommunicationHttpError("upload_conflict", "Controlled failure.", status_code=409)
    elif phase == "complete":
        boundary.facade.complete_failure = CommunicationHttpError("upload_conflict", "Controlled failure.", status_code=409)
    elif phase == "schema":
        boundary.facade.invalid_complete = True
    else:
        boundary.facade.revoke_complete = True
    response = put(boundary)
    assert response.status_code in {401, 409, 503} and response.json()["error"]["effect_state"] == "committed"
    assert "private_data" not in response.text and "must not leak" not in response.text


def test_download_is_verified_binary_with_safe_exact_headers_and_final_auth(boundary):
    response = request(boundary, "GET", "/" + ID + "/content")
    assert response.status_code == 200 and response.content == DATA
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-length"] == "10"
    assert response.headers["content-disposition"] == 'attachment; filename="fixture.png"'
    assert response.headers["x-content-type-options"] == "nosniff" and response.headers["cache-control"] == "no-store"
    assert response.headers["etag"] == '"' + hashlib.sha256(DATA).hexdigest() + '"'
    assert boundary.refresh_calls >= 2 and boundary.auth_calls >= 3
    boundary.facade.revoke_download = True
    revoked = request(boundary, "GET", "/" + ID + "/content")
    assert revoked.status_code == 401 and DATA not in revoked.content


def test_download_rejects_ranges_and_corrupt_backend_data_without_emitting_bytes(boundary):
    for header in ({"Range": "bytes=0-2"}, {"If-Range": '"etag"'}):
        response = request(boundary, "GET", "/" + ID + "/content", headers=header)
        assert response.status_code == 400 and boundary.facade.calls == []
    boundary.facade.corrupt_download = True
    response = request(boundary, "GET", "/" + ID + "/content")
    assert response.status_code == 503 and DATA not in response.content


def test_upload_and_download_reject_unknown_queries_after_auth(boundary):
    for method in ("PUT", "GET"):
        response = request(boundary, method, "/" + ID + "/content?path=/private/file", content=DATA,
            headers={"Idempotency-Key": "stable", "Content-Type": "application/octet-stream"})
        assert response.status_code == 400 and boundary.facade.calls == [] and boundary.auth_calls > 0
