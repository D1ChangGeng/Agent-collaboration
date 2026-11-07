"""Enrollment snapshot lock policy with actual helper control flow, no PG."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from nacl.signing import SigningKey

from runtime.enrollment import EnrollmentAuthority
from runtime.errors import AuthorizationDenied
from runtime.models import AuthenticatedContext
from runtime.receiver_crypto import key_fingerprint, public_key

NOW = datetime(2026, 11, 7, tzinfo=UTC)


@pytest.fixture(params=["owner", "shared"])
def graph(request):
    until = NOW + timedelta(hours=1)
    key = public_key(SigningKey.generate())
    state = SimpleNamespace(mode=request.param, calls=[], revoked=set())
    state.runtime = {"tenant_id": "tenant", "runtime_id": "runtime", "node_id": "node", "status": "active",
        "scope_id": "scope", "agent_slot_id": "slot", "node_binding_revision": 3, "node_boot_incarnation": "boot",
        "observer_ref": "observer", "observer_grant_ref": "observer-grant", "producer_ref": "producer",
        "producer_grant_ref": "producer-grant", "expires_at": until.isoformat()}
    state.node = {"tenant_id": "tenant", "node_id": "node", "status": "active", "scope_id": "scope",
        "agent_slot_id": "slot", "current_binding_revision": 3, "authority_id": "authority",
        "authority_incarnation": "incarnation", "observer_ref": "observer", "observer_grant_ref": "observer-grant"}
    state.binding = {"tenant_id": "tenant", "node_id": "node", "binding_revision": 3,
        "key_id": "node-key", "machine_id": "machine", "boot_incarnation": "boot", "expires_at": until.isoformat()}
    state.key = {"key_id": "node-key", "public_key": key, "fingerprint": key_fingerprint(key)}

    class Cursor:
        def execute(self, sql, params):
            state.calls.append((sql, params))
            if "FROM enrolled_runtimes" in sql:
                self.rows = [(deepcopy(state.runtime),)]
            elif "FROM enrolled_nodes" in sql:
                self.rows = [(deepcopy(state.node),)]
            elif "FROM enrolled_node_bindings" in sql:
                self.rows = [(deepcopy(state.binding), deepcopy(state.key))]
            elif "FROM agent_slots" in sql:
                self.rows = [(1,)]
            elif "FROM grants g" in sql:
                ref = params[2] if state.mode == "owner" else params[1]
                principal = {"observer-grant": "observer", "producer-grant": "producer"}[ref]
                self.rows = [] if ref in state.revoked else [(principal,)] if state.mode == "owner" else [(principal, until, [])]
            else:
                raise AssertionError("unexpected enrollment query")

        def fetchone(self):
            return self.rows[0] if self.rows else None

    authority = SimpleNamespace(tenant_id="tenant", access_mode=state.mode,
        context=AuthenticatedContext("tenant", "authority", "incarnation", "caller", "caller-grant"))
    state.reader, state.cursor = EnrollmentAuthority(authority), Cursor()
    return state


def test_current_snapshot_uses_compatible_read_locks_without_upgrade_waits(graph):
    runtime, node, binding, key, expiry = graph.reader.current_runtime_snapshot(graph.cursor, "runtime")
    assert runtime == graph.runtime and node == graph.node and binding == graph.binding and key == graph.key
    assert all("FOR SHARE" in sql and sql.endswith(" NOWAIT") for sql, _params in graph.calls)
    grants = [sql for sql, _params in graph.calls if "FROM grants g" in sql]
    assert len(grants) == 2
    assert all("a.status='active'" in sql and "FOR SHARE OF g,a,s NOWAIT" in sql for sql in grants)
    assert expiry is None if graph.mode == "owner" else expiry == NOW + timedelta(hours=1)
    assert not getattr(graph.reader, "_snapshot_read", False)


def test_existing_mutation_reader_keeps_its_original_lock_policy(graph):
    graph.reader._active_runtime(graph.cursor, "runtime")
    assert graph.calls[0][0].endswith(" FOR UPDATE")
    assert not any("NOWAIT" in sql for sql, _params in graph.calls)
    grants = [sql for sql, _params in graph.calls if "FROM grants g" in sql]
    if graph.mode == "owner":
        assert all("FOR SHARE" not in sql for sql in grants)
    else:
        assert all(sql.endswith("FOR SHARE OF g,a,s") for sql in grants)


@pytest.mark.parametrize("revoked", ["observer-grant", "producer-grant"])
def test_snapshot_requires_current_observer_and_producer_even_in_owner_mode(graph, revoked):
    graph.revoked.add(revoked)
    with pytest.raises(AuthorizationDenied):
        graph.reader.current_runtime_snapshot(graph.cursor, "runtime")


def test_snapshot_does_not_swallow_lock_conflict_or_fall_back_to_unlocked_authority(graph):
    calls = []

    def conflict(sql, _params):
        calls.append(sql)
        raise TimeoutError("controlled NOWAIT conflict; caller must roll back")

    graph.cursor.execute = conflict
    with pytest.raises(TimeoutError):
        graph.reader.current_runtime_snapshot(graph.cursor, "runtime")
    assert len(calls) == 1 and "FOR SHARE NOWAIT" in calls[0]
