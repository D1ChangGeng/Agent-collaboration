"""Real mounted OAuth attachment HTTP, isolated PG staging and platform CAS.

Only issuer introspection is synthetic. No DTO/event is injected and no model,
Native input, Agent reply or deployed contact is involved.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

import httpx
import psycopg
import pytest

import runtime.communication_client_attachments as facade_module
from runtime.client_contracts import ClientContracts
from runtime.project_http import ProjectHttpSettings
from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_attachment_content import png
from runtime_tests.test_communication_client_attachments import attached as attached_fixture
from runtime_tests.test_communication_client_attachments import bind, declare, row
from runtime_tests.test_communication_client_oauth import app_for, explicit_initialize
from runtime_tests.test_notification_continuity import shared_principal_clients
from runtime_tests.test_project_http import IssuerFixture, claims, settings

comm, attached = comm_fixture, attached_fixture
PROJECT, PREFIX = "project-alpha", "/api/communication/v1"
BASE = PREFIX + f"/projects/{PROJECT}/attachments"
CONTRACTS = ClientContracts()


@pytest.fixture(scope="session", autouse=True)
def frozen_source_fingerprints():
    root = Path(__file__).resolve().parents[1]
    paths = ("runtime/communication_client_attachments.py", "runtime/communication_attachment_content.py",
        "runtime/communication_attachment_storage.py", "runtime/communication_attachment_schema.sql",
        "runtime/communication_client_service.py", "runtime/communication_http.py", "runtime/communication_attachment_http.py",
        "runtime/communication_client_oauth.py", "runtime/project_http.py", "runtime/project_service.py",
        "runtime/project_schema_state.py", "runtime/surface_config.py", "runtime/models.py")
    before = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}
    print(json.dumps({"source_fingerprints": before}, sort_keys=True))
    yield
    assert {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths} == before, "tested sources changed during the frozen run"


def bearer(actor="a"):
    return {"Authorization": "Bearer live-" + actor}


@asynccontextmanager
async def live(f, monkeypatch, *, enabled=True):
    data = settings(monkeypatch, f.authority.context).model_dump()
    data.update(communication_client_api=True, communication_attachments=enabled, authorization_refresh_seconds=5)
    data["bindings"] = []
    tokens = {}
    for name, source in f.clients.items():
        context = source.service.context
        slot = context.agent_slot_id or ("local-slot" if name == "a" else "slot-" + name)
        subject = "attachment-subject-" + name
        data["bindings"].append({"subject": subject, "client_id": "web-client", "profile": source.service.profile,
            "principal_ref": context.principal_ref, "grant_ref": context.grant_ref, "agent_slot_id": slot, "trusted_client": False})
        tokens["live-" + name] = claims(sub=subject)
    cfg = ProjectHttpSettings.model_validate(data)
    issuer = IssuerFixture(tokens)
    async with issuer.client() as issuer_client:
        app = app_for(f, cfg, issuer_client)
        explicit_initialize(f)
        async with (app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8765") as http):
            yield app, http


async def reserve(http, data, *, key="reserve", actor="a", media_type="text/plain", name="notes.txt"):
    response = await http.post(BASE, headers=bearer(actor) | {"Idempotency-Key": key}, json=declare(data, media_type=media_type, name=name))
    assert response.status_code == 201, response.text
    return CONTRACTS.validate("Attachment", response.json())


def fragments(data, sizes=(1, 7, 32769, 3, 60000)):
    async def generate():
        offset = 0
        for size in sizes:
            if offset >= len(data):
                break
            yield data[offset:offset + size]
            offset += size
        if offset < len(data):
            yield data[offset:]
    return generate()


async def upload(http, value, data, *, key="upload", actor="a", content_type="application/octet-stream"):
    return await http.put(BASE + "/" + value["attachment_id"] + "/content", headers=bearer(actor) |
        {"Idempotency-Key": key, "Content-Type": content_type}, content=fragments(data))


async def finalize(http, value, *, key="finalize", actor="a"):
    return await http.post(BASE + "/" + value["attachment_id"] + "/finalize", headers=bearer(actor) | {"Idempotency-Key": key},
                           json={"bytes": value["bytes"], "sha256": value["sha256"]})


def test_default_off_and_authentication_happen_before_incoming_body(attached, monkeypatch):
    async def exercise():
        async with live(attached, monkeypatch, enabled=False) as (_app, http):
            meta = await http.get(PREFIX + "/meta")
            assert meta.status_code == 200 and "attachment_uploads" not in meta.json()["features"]
            disabled = await http.post(BASE, headers=bearer() | {"Idempotency-Key": "disabled"}, json=declare(b"x"))
            assert disabled.status_code == 409 and disabled.json()["error"]["code"] == "capability_unsupported"
            touched = []

            async def hostile_body():
                touched.append(True)
                raise AssertionError("unauthenticated body was read")
                yield b""  # pragma: no cover - defines an asynchronous byte stream.

            for suffix, method, content_type in (("", "POST", "application/json"),
                ("/attachment-" + "0" * 32 + "/content", "PUT", "application/octet-stream")):
                response = await http.request(method, BASE + suffix, headers={"Idempotency-Key": "unauth", "Content-Type": content_type}, content=hostile_body())
                assert response.status_code == 401
            assert touched == []
    asyncio.run(exercise())


def test_actual_meta_reports_upload_only_capacities_not_message_attachment_support(attached, monkeypatch):
    async def exercise():
        async with live(attached, monkeypatch) as (_app, http):
            response = await http.get(PREFIX + "/meta")
            assert response.status_code == 200, response.text
            meta = CONTRACTS.validate("Meta", response.json())
            assert {"attachment_uploads", "attachments"} <= set(meta["features"])
            assert meta["limits"]["attachment_bytes"] == attached.attachment_settings.file_bytes
            assert meta["limits"]["attachment_staging_bytes"] == attached.attachment_settings.viewer_staging_bytes
            assert meta["limits"]["attachment_project_staging_bytes"] == attached.attachment_settings.project_staging_bytes
            assert meta["limits"]["attachment_staging_seconds"] == attached.attachment_settings.staging_seconds
            assert meta["limits"]["attachment_count"] == attached.attachment_settings.message_count
            assert meta["limits"]["attachment_total_bytes"] == attached.attachment_settings.message_bytes
    asyncio.run(exercise())


@pytest.mark.parametrize("data,media,name", [("汉字🧭 fragmented text".encode(), "text/plain; charset=UTF-8", "汉字 🧭.txt"),
    (b'{"actual":"json","value":[1,2]}', "application/json", "object.json"), (png(), "image/png", "pixel.png")], ids=["text", "json", "png"])
def test_real_fragmented_upload_finalize_verified_download_and_exact_outcomes(attached, monkeypatch, data, media, name):
    async def exercise():
        async with live(attached, monkeypatch) as (_app, http):
            value = await reserve(http, data, media_type=media, name=name)
            assert value["attachment_id"].startswith("attachment-") and value["sha256"] not in value["attachment_id"]
            first = await upload(http, value, data)
            assert first.status_code == 200, first.text
            uploaded = CONTRACTS.validate("Attachment", first.json())
            assert uploaded["state"] == "uploaded"
            completed = await finalize(http, value)
            assert completed.status_code == 200, completed.text
            ready = CONTRACTS.validate("Attachment", completed.json())
            assert ready["state"] == "ready"
            duplicate = await upload(http, value, data)
            assert duplicate.status_code == 200 and duplicate.json() == uploaded
            assert (await finalize(http, value)).json() == ready
            different = await upload(http, value, b"x" * len(data))
            assert different.status_code == 409 and different.json()["error"]["code"] == "idempotency_conflict"
            downloaded = await http.get(BASE + "/" + value["attachment_id"] + "/content", headers=bearer())
            assert downloaded.status_code == 200, downloaded.text
            assert downloaded.content == data and hashlib.sha256(downloaded.content).hexdigest() == value["sha256"]
            assert downloaded.headers["content-type"] == media.split(";")[0]
            assert downloaded.headers["x-content-type-options"] == "nosniff"
            assert downloaded.headers["cache-control"] == "no-store" and downloaded.headers["accept-ranges"] == "none"
            header = downloaded.headers["content-disposition"]
            assert header.isascii() and unquote(header.split("UTF-8''", 1)[1]) == name
            assert downloaded.headers["etag"] == '"' + value["sha256"] + '"'
            partial = await http.get(BASE + "/" + value["attachment_id"] + "/content", headers=bearer() | {"Range": "bytes=0-1"})
            assert partial.status_code == 400
    asyncio.run(exercise())
    assert not any(driver.calls for driver in attached.drivers.values())
    with psycopg.connect(attached.dsn) as connection:
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone()[0] == 0


def test_transport_type_streaming_bounds_and_validation_rejections_are_not_ready(attached, monkeypatch):
    async def exercise():
        async with live(attached, monkeypatch) as (_app, http):
            value = await reserve(http, b"declared")
            wrong_header = await upload(http, value, b"declared", content_type="text/plain")
            assert wrong_header.status_code == 400
            assert row(attached, value["attachment_id"])["state"] == "reserved"
            wrong_digest = await upload(http, value, b"DECLARED")
            assert wrong_digest.status_code == 400
            assert row(attached, value["attachment_id"])["state"] == "rejected"
            small = await reserve(http, b"xx", key="small-stream")
            overflow = await upload(http, small, b"xxx", key="overflow-stream")
            assert overflow.status_code == 413
            assert row(attached, small["attachment_id"])["state"] != "ready"
            over = await http.post(BASE, headers=bearer() | {"Idempotency-Key": "oversize-reserve"},
                json=declare(b"x") | {"bytes": attached.attachment_settings.file_bytes + 1})
            assert over.status_code == 413
            image = await reserve(http, b"not png", key="invalid-image", media_type="image/png", name="image.png")
            assert (await upload(http, image, b"not png", key="invalid-image-upload")).status_code == 200
            rejected = await finalize(http, image, key="invalid-image-finalize")
            assert rejected.status_code == 400
            assert row(attached, image["attachment_id"])["state"] == "rejected"
            repeated = await finalize(http, image, key="invalid-image-finalize")
            assert repeated.status_code == 400 and repeated.json()["error"] == rejected.json()["error"]
    asyncio.run(exercise())


def test_same_principal_slots_and_manager_have_no_http_staging_access(attached, monkeypatch):
    shared_principal_clients(attached)
    bind(attached)

    async def exercise():
        async with live(attached, monkeypatch) as (_app, http):
            value = await reserve(http, b"private shared principal staging", actor="shared-1")
            for other in ("shared-2", "a", "b", "c"):
                denied = await http.get(BASE + "/" + value["attachment_id"], headers=bearer(other))
                assert denied.status_code == 404 and denied.json()["error"]["code"] == "not_found"
                upload_denied = await upload(http, value, b"private shared principal staging", actor=other)
                assert upload_denied.status_code == 404
            own = await http.get(BASE + "/" + value["attachment_id"], headers=bearer("shared-1"))
            assert own.status_code == 200 and own.json() == value
    asyncio.run(exercise())


def test_fragment_stream_and_cas_have_no_request_wide_sql_locks(attached, monkeypatch):
    data = b"x" * 65536 + b"last"
    original = facade_module.put_attachment_content
    observed = []

    def no_sql_cas(*args, **kwargs):
        with psycopg.connect(attached.dsn) as writer:
            writer.execute("SELECT attachment_id FROM communication_attachments FOR UPDATE NOWAIT")
            writer.execute("SELECT grant_ref FROM grants WHERE grant_ref=%s FOR UPDATE NOWAIT", (attached.authority.context.grant_ref,))
        observed.append("cas")
        return original(*args, **kwargs)

    monkeypatch.setattr(facade_module, "put_attachment_content", no_sql_cas)

    async def exercise():
        async with live(attached, monkeypatch) as (_app, http):
            value = await reserve(http, data)

            async def incoming():
                with psycopg.connect(attached.dsn) as writer:
                    writer.execute("SELECT attachment_id FROM communication_attachments WHERE attachment_id=%s FOR UPDATE NOWAIT", (value["attachment_id"],))
                observed.append("stream")
                yield data[:3]
                yield data[3:65537]
                yield data[65537:]

            response = await http.put(BASE + "/" + value["attachment_id"] + "/content", headers=bearer() |
                {"Idempotency-Key": "stream-unlocked", "Content-Type": "application/octet-stream"}, content=incoming())
            assert response.status_code == 200, response.text
            finalized = await finalize(http, value)
            assert finalized.status_code == 200, finalized.text
    asyncio.run(exercise())
    assert observed == ["stream", "cas"]


@pytest.mark.parametrize("phase", ["ready", "download"])
def test_live_domain_grant_or_artifact_permission_revocation_prevents_data(attached, monkeypatch, phase):
    original_put, original_read = facade_module.put_attachment_content, facade_module.read_attachment_content

    def revoke_put(*args, **kwargs):
        artifact = original_put(*args, **kwargs)
        if phase == "ready":
            with psycopg.connect(attached.dsn) as connection:
                connection.execute("UPDATE grants SET revoked_at=clock_timestamp() WHERE grant_ref=%s", (attached.authority.context.grant_ref,))
        return artifact

    def revoke_read(*args, **kwargs):
        data = original_read(*args, **kwargs)
        with psycopg.connect(attached.dsn) as connection:
            connection.execute("UPDATE grants SET permissions=permissions-'artifact.read' WHERE grant_ref=%s", (attached.authority.context.grant_ref,))
        return data

    monkeypatch.setattr(facade_module, "put_attachment_content", revoke_put)
    if phase == "download":
        monkeypatch.setattr(facade_module, "read_attachment_content", revoke_read)

    async def exercise():
        async with live(attached, monkeypatch) as (_app, http):
            value = await reserve(http, b"revocation HTTP boundary")
            assert (await upload(http, value, b"revocation HTTP boundary")).status_code == 200
            final = await finalize(http, value)
            if phase == "ready":
                assert final.status_code == 403
                assert row(attached, value["attachment_id"])["state"] == "uploaded"
            else:
                assert final.status_code == 200
                download = await http.get(BASE + "/" + value["attachment_id"] + "/content", headers=bearer())
                assert download.status_code == 403 and download.headers["content-type"].startswith("application/json")
                assert b"revocation HTTP boundary" not in download.content
    asyncio.run(exercise())


def test_real_asgi_disconnect_retains_exact_chunks_and_full_retry_resumes_original_plan(attached, monkeypatch):
    data = b"x" * 65536 + b"retry remainder"

    async def exercise():
        async with live(attached, monkeypatch) as (app, http):
            value = await reserve(http, data)
            path = BASE + "/" + value["attachment_id"] + "/content"
            messages = iter(({"type": "http.request", "body": data[:65536], "more_body": True}, {"type": "http.disconnect"}))
            sent = []

            async def receive():
                return next(messages, {"type": "http.disconnect"})

            async def send_message(message):
                sent.append(message)

            scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
                "method": "PUT", "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
                "headers": [(b"host", b"127.0.0.1:8765"), (b"authorization", b"Bearer live-a"),
                    (b"content-type", b"application/octet-stream"), (b"idempotency-key", b"disconnect-retry")],
                "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 8765)}
            await app(scope, receive, send_message)
            actual = row(attached, value["attachment_id"])
            assert actual["state"] == "reserved" and actual["received_bytes"] == 65536
            assert not any(message.get("body", b"") == data for message in sent)
            retried = await upload(http, value, data, key="disconnect-retry")
            assert retried.status_code == 200, retried.text
            assert (await finalize(http, value)).status_code == 200
            downloaded = await http.get(path, headers=bearer())
            assert downloaded.status_code == 200 and downloaded.content == data
    asyncio.run(exercise())
