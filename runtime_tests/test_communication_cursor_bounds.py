"""Legal configuration bounds fit opaque cursors and metadata identities.

Pure codec tests patch only the private key lookup, not the encoder/decoder or
RoleContext validation. The optional PostgreSQL case is trusted storage testing,
not qualification of Unicode Domain authentication or a complete client API.
"""
from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace

import psycopg
import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

import runtime.communication_client_events as event_module
from runtime.client_contracts import ClientContracts
from runtime.communication_client_events import ClientEventFeed, encode_event_cursor
from runtime.communication_client_storage import (
    ClientStateIdentity,
    adopt_client_storage,
    read_preferences,
    write_preferences,
)
from runtime.communication_event_storage import KINDS
from runtime.communication_http import CommunicationHttpError
from runtime.communication_snapshot_storage import (
    SnapshotIdentity,
    adopt_snapshot_storage,
    read_snapshot,
    save_snapshot,
    snapshot_filter_digest,
)
from runtime.surface_config import RoleContext
from runtime_tests.test_communication import comm as comm_fixture

comm = comm_fixture
PROJECT = "p" * 128
AUTH_REVISION = "a" * 64
POSITION = 2**63 - 1
TENANT = "🧭" * 256


def role_context(**changes):
    return RoleContext.model_validate({"tenant_id": TENANT, "authority_id": "cursor-bounds-authority",
        "authority_incarnation": "cursor-bounds-incarnation", "principal_ref": "cursor-bounds-principal",
        "grant_ref": "cursor-bounds-grant", "credential_hash": "0" * 64,
        "agent_slot_id": "cursor-bounds-slot", "trusted_client": False, **changes})


@pytest.fixture
def codec(monkeypatch):
    context = role_context()
    connection = object()

    def private_key(selected):
        assert selected is connection
        return b"k" * 32

    monkeypatch.setattr(event_module, "cursor_secret", private_key)
    feed = ClientEventFeed()
    feed.authority = SimpleNamespace(tenant_id=context.tenant_id)
    return SimpleNamespace(context=context, cursor=SimpleNamespace(connection=connection), feed=feed,
                           kinds=feed._event_kinds(list(KINDS)))


def test_maximum_legal_role_tenant_and_registry_cursor_fit_wire_contracts(codec):
    assert len(codec.context.tenant_id) == 256 and len(codec.context.tenant_id.encode("utf-8")) == 1024
    assert len(codec.kinds) == 15
    with pytest.raises(ValidationError):
        role_context(tenant_id="🧭" * 257)
    token = encode_event_cursor(codec.cursor, codec.context.tenant_id, PROJECT, AUTH_REVISION, POSITION, kinds=codec.kinds)
    assert len(token) <= 2048
    assert codec.feed._decode_event_cursor(codec.cursor, PROJECT, token, AUTH_REVISION, codec.kinds) == POSITION
    event = {"schema_version": "acs-event/1", "event_id": "fixture-event", "cursor": token,
        "project_id": PROJECT, "kind": "stream.end", "resource_ref": None, "resource_revision": 0,
        "committed_at": "2026-11-06T00:00:00+00:00", "auth_revision": AUTH_REVISION,
        "payload": {"reason_code": "synthetic-cursor-boundary-fixture"}}
    assert ClientContracts().validate("Event", event) == event
    # Check the real Snapshot field contract without constructing an unrelated
    # Actor/metadata snapshot merely to test its cursor envelope.
    after_cursor = ClientContracts().schema("Snapshot")["$defs"]["Snapshot"]["properties"]["after_cursor"]
    Draft202012Validator(after_cursor).validate(token)


def test_anchor_can_start_default_or_filtered_replay_and_default_cursor_keeps_filter(codec):
    anchor = encode_event_cursor(codec.cursor, codec.context.tenant_id, PROJECT, AUTH_REVISION, POSITION, anchor=True)
    for selected in (None, codec.kinds, codec.kinds[:1]):
        assert codec.feed._decode_event_cursor(codec.cursor, PROJECT, anchor, AUTH_REVISION, selected) == POSITION
    default = encode_event_cursor(codec.cursor, codec.context.tenant_id, PROJECT, AUTH_REVISION, POSITION)
    assert codec.feed._decode_event_cursor(codec.cursor, PROJECT, default, AUTH_REVISION, None) == POSITION
    with pytest.raises(CommunicationHttpError) as changed:
        codec.feed._decode_event_cursor(codec.cursor, PROJECT, default, AUTH_REVISION, codec.kinds)
    assert changed.value.code == "cursor_invalid" and changed.value.status_code == 409


@pytest.mark.parametrize("changed", ["tenant", "project", "authorization", "kinds", "unfiltered"])
def test_valid_cursor_signature_does_not_allow_namespace_auth_or_filter_change(codec, changed):
    token = encode_event_cursor(codec.cursor, codec.context.tenant_id, PROJECT, AUTH_REVISION, POSITION, kinds=codec.kinds)
    project, revision, selected = PROJECT, AUTH_REVISION, codec.kinds
    if changed == "tenant":
        codec.feed.authority.tenant_id = "🧭" * 255 + "界"
    elif changed == "project":
        project = "p" * 127 + "q"
    elif changed == "authorization":
        revision = "b" * 64
    elif changed == "kinds":
        selected = codec.kinds[:-1]
    else:
        selected = None
    with pytest.raises(CommunicationHttpError) as mismatch:
        codec.feed._decode_event_cursor(codec.cursor, project, token, revision, selected)
    assert mismatch.value.code == "cursor_invalid" and mismatch.value.status_code == 409


@pytest.mark.parametrize("field", ["tenant_id", "project_id", "actor_ref", "conversation_id"])
def test_personal_identity_limits_are_unicode_characters(field):
    values = {"tenant_id": "t", "project_id": "p", "actor_ref": "a", "conversation_id": "c"}
    values[field] = "🧭" * 512
    selected = ClientStateIdentity(**values)
    assert getattr(selected, field) == "🧭" * 512
    with pytest.raises(ValueError):
        replace(selected, **{field: "🧭" * 513})


@pytest.mark.parametrize("field", ["tenant_id", "project_id", "viewer_key", "auth_revision"])
def test_snapshot_identity_limits_are_unicode_characters(field):
    values = {"tenant_id": "t", "project_id": "p", "viewer_key": "v", "auth_revision": "a",
              "filter_digest": snapshot_filter_digest({})}
    values[field] = "🧭" * 512
    selected = SnapshotIdentity(**values)
    assert getattr(selected, field) == "🧭" * 512
    with pytest.raises(ValueError):
        replace(selected, **{field: "🧭" * 513})


def test_trusted_storage_roundtrip_supports_legal_unicode_tenant_without_auth_claim(comm):
    context = role_context()
    scope, root = "cursor-scope-" + uuid.uuid4().hex, "cursor-root-" + uuid.uuid4().hex
    viewer, conversation = "viewer-" + "c" * 64, "conversation-" + "d" * 64
    with psycopg.connect(comm.dsn) as connection, connection.cursor() as cursor:
        adopt_client_storage(connection)
        adopt_snapshot_storage(connection)
        cursor.execute("INSERT INTO scopes VALUES (%s,%s,'{}','active')", (scope, context.tenant_id))
        cursor.execute("INSERT INTO collaboration_projects(tenant_id,project_id,root_id,scope_id,name,context_manifest) VALUES (%s,%s,%s,%s,'Unicode storage boundary','{}')",
                       (context.tenant_id, PROJECT, root, scope))
        private = ClientStateIdentity(context.tenant_id, PROJECT, viewer, conversation)
        assert write_preferences(cursor, private, {"muted": True}, expected_revision=0, client_request_id="unicode-storage") == {"archived": False, "muted": True, "revision": 1}
        assert read_preferences(cursor, private)["muted"] is True
        snapshot_owner = SnapshotIdentity(context.tenant_id, PROJECT, viewer, AUTH_REVISION, snapshot_filter_digest({}))
        projection = {"actor": {"address": f"collaborator:{PROJECT}:{context.agent_slot_id}", "principal_ref": context.principal_ref,
            "level": "agent", "agent_slot_id": context.agent_slot_id, "auth_revision": AUTH_REVISION, "allowed_actions": []}, "notice_count": 0}
        meta = save_snapshot(cursor, snapshot_owner, projection, {"contacts": [], "conversations": [], "receivers": []}, high_water=0)
        assert read_snapshot(cursor, snapshot_owner, meta["snapshot_ref"]) == meta
