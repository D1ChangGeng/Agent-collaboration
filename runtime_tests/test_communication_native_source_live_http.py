"""Mounted OAuth/actual TCP + SDK/PG/original Driver journal, controlled Native.

No model, Native process or real issuer/Host is contacted. Source DTOs are
derived by the production service; no source link is injected into a response.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from runtime_tests.test_communication import comm as comm_fixture
from runtime_tests.test_communication_client_native_source import source as source_fixture
from runtime_tests.test_communication_native_link_live_http import tcp_listener

comm, source = comm_fixture, source_fixture
ROOT = Path(__file__).resolve().parents[1]


def test_actual_oauth_tcp_query_and_production_sdk_return_original_protocol_references(source, monkeypatch):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for actual production SDK consumer")
    before = len(source.wire.calls)
    with tcp_listener(source, monkeypatch) as url:
        route = url + "/api/communication/v1/projects/project-alpha/messages/" + quote(source.submitted["message_handle"], safe="")
        with httpx.Client(trust_env=False, timeout=15) as http:
            assert http.get(route + "?include_native_source=true").status_code == 401
            denied = http.get(route + "?include_native_source=true", headers={"Authorization": "Bearer link-c"})
            assert denied.status_code == 403 and denied.json()["error"]["effect_state"] == "none"
            missing_scope = http.get(route + "?include_native_source=true", headers={"Authorization": "Bearer link-b-read"})
            assert missing_scope.status_code == 403
            invalid = http.get(route + "?include_native_source=yes", headers={"Authorization": "Bearer link-a"})
            assert invalid.status_code == 400 and invalid.json()["error"]["effect_state"] == "none"
            assert http.get(route + "?provider_url=http://untrusted.invalid", headers={"Authorization": "Bearer link-a"}).status_code == 400
        environment = dict(os.environ)
        environment["ACS_NATIVE_SOURCE_TEST_TOKEN"] = "link-a"
        result = subprocess.run([node, str(ROOT / "sdk/tests/native-source-live-consumer.mjs"),
            url + "/api/communication/v1/", "project-alpha", source.submitted["message_handle"],
            source.submitted["operation_id"], source.protocol], env=environment, cwd=ROOT,
            capture_output=True, text=True, timeout=45, check=False)
        assert result.returncode == 0, result.stderr
        recorded = json.loads(result.stdout)
        assert recorded["available"] is True and recorded["operation_id"] == source.submitted["operation_id"]
        assert recorded["tcp"] is True and recorded["sdk"] == "production"
    assert len(source.wire.calls) == before


def test_actual_acs_with_controlled_host_delegate_keeps_provenance_nonce_and_native_settings_separate(source, monkeypatch):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for actual ACS and controlled Host port consumer")
    before = len(source.wire.calls)
    with source.f.authority._connect() as connection:
        messages = connection.execute("SELECT message_id,packet_json FROM delivery_messages ORDER BY message_id").fetchall()
        replies = connection.execute("SELECT count(*) FROM communication_replies").fetchone()
    with tcp_listener(source, monkeypatch) as url:
        environment = dict(os.environ)
        environment["ACS_NATIVE_SOURCE_TEST_TOKEN"] = "link-a"
        result = subprocess.run([node, str(ROOT / "sdk/tests/native-delegate-live-consumer.mjs"),
            url + "/api/communication/v1/", "project-alpha", source.submitted["message_handle"]],
            env=environment, cwd=ROOT, capture_output=True, text=True, timeout=45, check=False)
        assert result.returncode == 0, result.stderr
        recorded = json.loads(result.stdout)
        assert all(recorded[key] for key in ("same_text_unlinked", "stale_nonce_denied", "replaced_turn_denied",
            "independent_native_cursor", "settings_did_not_change_sender", "clear_compact_preserved_acs_history",
            "child_acl_enforced", "child_source_unlinked"))
        assert recorded["physical_host_qualified"] is recorded["model_request"] is False
    with source.f.authority._connect() as connection:
        assert connection.execute("SELECT message_id,packet_json FROM delivery_messages ORDER BY message_id").fetchall() == messages
        assert connection.execute("SELECT count(*) FROM communication_replies").fetchone() == replies == (0,)
    assert len(source.wire.calls) == before
