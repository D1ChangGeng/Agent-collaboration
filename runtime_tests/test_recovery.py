from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from runtime.recovery import (
    DriverCollectorAdapter,
    InvocationCollectionIdentity,
    NodeResponseOutbox,
    ProjectionDisposition,
)
from runtime.recovery_models import (
    BoundaryRejected,
    DispatchIdentity,
    NativeResponseObservation,
    StateConflict,
    response_receipt_id,
)

DIGEST = "a" * 64


def identity(**changes):
    value = DispatchIdentity(
        "tenant", "message", "operation", "invocation", "attempt", "dispatch",
        "endpoint", 1, "machine", "node", "boot", 7, DIGEST,
    )
    return replace(value, **changes)


def observation(**changes):
    dispatch = changes.get("identity", identity())
    projection_id = changes.get("projection_id", "projection")
    value = NativeResponseObservation(
        projection_id, response_receipt_id(dispatch, projection_id), dispatch,
        "native-response", "completed",
        "artifact:response", "c" * 64, "b" * 64, datetime.now(UTC),
    )
    return replace(value, **changes)


class FixtureDriver:
    def __init__(self, result=None):
        self.collect_calls = 0
        self.invoke_calls = 0
        self.result = result or {
            "receipt_layer": "response_received",
            "operation_id": "operation",
            "command_id": "command",
            "message_id": "message",
            "invocation_id": "invocation",
            "attempt_id": "attempt",
            "dispatch_id": "dispatch",
            "binding_id": "binding",
            "binding": {"node_id": "node", "node_boot_id": "boot", "runtime_id": "runtime",
                        "attempt_id": "attempt", "agent_slot_id": "slot", "revision": 1},
            "session_id": "session",
            "thread_id": "thread",
            "turn_id": "turn-1",
            "native_status": "completed",
            "native_terminal_observed_at": "2026-09-12T00:00:00+00:00",
            "observed_at": "2026-09-12T00:01:00+00:00",
            "assistant_messages": [{"id": "answer-1"}],
        }

    def collect_result(self, operation, invocation_operation_id):
        self.collect_calls += 1
        if invocation_operation_id != "operation":
            raise AssertionError("wrong invocation operation")
        return dict(self.result)

    def invoke(self, *_args, **_kwargs):
        self.invoke_calls += 1
        raise AssertionError("collector must never invoke")


def collection(**changes):
    values = {
        "dispatch": identity(), "command_id": "command", "binding_id": "binding",
        "binding_items": (("node_id", "node"), ("node_boot_id", "boot"),
                          ("runtime_id", "runtime"), ("attempt_id", "attempt"),
                          ("agent_slot_id", "slot"), ("revision", 1)),
        "driver_kind": "codex", "native_session_ref": "session",
        "native_thread_ref": "thread", "native_turn_ref": "turn-1",
    }
    values.update(changes)
    return InvocationCollectionIdentity(**values)


class NodeResponseOutboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "node.sqlite"
        self.outbox = NodeResponseOutbox(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_record_replay_restart_and_mark(self):
        item = observation()
        self.assertTrue(self.outbox.record(item))
        self.assertFalse(self.outbox.record(item))
        recovered = NodeResponseOutbox(self.path)
        self.assertEqual(recovered.pending(), (item,))
        self.assertEqual(len(recovered.recover()), 1)
        recovered.mark(ProjectionDisposition(
            item.projection_id, NodeResponseOutbox._payload(item)[1], "applied",
        ))
        self.assertEqual(recovered.pending(), ())
        self.assertEqual(recovered.recover(), ())

    def test_projection_receipt_and_native_identity_conflicts_are_atomic(self):
        first = observation()
        self.outbox.record(first)
        for changed in (
            observation(evidence_digest="c" * 64),
            observation(projection_id="other", native_response_ref="other-native"),
        ):
            with self.subTest(changed=changed), self.assertRaises(StateConflict):
                self.outbox.record(changed)
        with self.assertRaises(BoundaryRejected):
            self.outbox.record(observation(projection_id="other", receipt_id="other-receipt"))
        self.assertEqual(self.outbox.pending(), (first,))

    def test_failed_projection_remains_recoverable(self):
        item = observation()
        self.outbox.record(item)
        self.outbox.fail(item.projection_id, "transport_unavailable")
        recovered = self.outbox.recover()
        self.assertEqual(recovered[0]["attempts"], 1)
        self.assertEqual(recovered[0]["last_error"], "transport_unavailable")

    def test_wrong_domain_disposition_has_no_side_effect(self):
        item = observation()
        self.outbox.record(item)
        with self.assertRaises(StateConflict):
            self.outbox.mark(ProjectionDisposition(item.projection_id, "c" * 64, "applied"))
        self.assertEqual(self.outbox.pending(), (item,))

    def test_concurrent_exact_record_commits_once(self):
        item = observation()
        results = []
        errors = []

        def record():
            try:
                results.append(self.outbox.record(item))
            except (sqlite3.Error, StateConflict) as error:
                errors.append(error)

        threads = [threading.Thread(target=record) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(results), [False, False, False, True])
        self.assertEqual(self.outbox.pending(), (item,))

    def test_collector_calls_only_collect_result_and_persists_terminal(self):
        driver = FixtureDriver()
        result = DriverCollectorAdapter(
            driver, self.outbox, lambda _value: ("artifact:fixture", "d" * 64),
        ).collect(
            object(), "operation", collection(),
        )
        self.assertEqual(driver.collect_calls, 1)
        self.assertEqual(driver.invoke_calls, 0)
        self.assertEqual(self.outbox.pending(), (result,))

    def test_collector_rejects_wrong_or_nonterminal_lineage_without_outbox(self):
        for result in (
            {"receipt_layer": "runtime_acknowledged", "operation_id": "operation",
             "message_id": "message", "turn_id": "turn", "native_status": "inProgress"},
            {"receipt_layer": "response_received", "operation_id": "other",
             "message_id": "message", "turn_id": "turn", "native_status": "completed"},
        ):
            with self.subTest(result=result), self.assertRaises(BoundaryRejected):
                DriverCollectorAdapter(
                    FixtureDriver(result), self.outbox,
                    lambda _value: ("artifact:fixture", "d" * 64),
                ).collect(
                    object(), "operation", collection(),
                )
        self.assertEqual(self.outbox.pending(), ())

    def test_collector_reuses_first_persisted_terminal_without_new_timestamp(self):
        driver = FixtureDriver()
        stored = []

        def persist(value):
            stored.append(value)
            return "artifact:fixture", "d" * 64

        adapter = DriverCollectorAdapter(driver, self.outbox, persist)
        first = adapter.collect(object(), "operation", collection())
        driver.result["observed_at"] = "2026-09-12T00:02:00+00:00"
        second = adapter.collect(object(), "operation", collection())
        self.assertEqual(first, second)
        self.assertEqual(driver.collect_calls, 1)
        self.assertEqual(len(stored), 1)

        restarted_driver = FixtureDriver()
        restarted_store = []
        restarted = DriverCollectorAdapter(
            restarted_driver, NodeResponseOutbox(self.path),
            lambda value: (restarted_store.append(value) or "artifact:other", "e" * 64),
        )
        self.assertEqual(restarted.collect(object(), "operation", collection()), first)
        self.assertEqual(restarted_driver.collect_calls, 0)
        self.assertEqual(restarted_store, [])

    def test_collector_cache_hit_requires_complete_dispatch_identity(self):
        self.outbox.record(observation())
        changed = identity(dispatch_id="different-dispatch")
        driver = FixtureDriver()
        with self.assertRaises(StateConflict):
            DriverCollectorAdapter(
                driver, self.outbox,
                lambda _value: ("artifact:fixture", "d" * 64),
            ).collect(object(), "operation", collection(dispatch=changed))
        self.assertEqual(driver.collect_calls, 0)

    def test_collection_binding_revision_must_equal_dispatch_revision(self):
        with self.assertRaises(BoundaryRejected):
            collection(binding_items=(
                ("node_id", "node"), ("node_boot_id", "boot"),
                ("runtime_id", "runtime"), ("attempt_id", "attempt"),
                ("agent_slot_id", "slot"), ("revision", 99),
            ))

    def test_opencode_collector_binds_native_message_and_session(self):
        result = dict(FixtureDriver().result)
        result.pop("session_id")
        result.pop("thread_id")
        result.pop("turn_id")
        result["native_session_id"] = "session"
        result["native_message_id"] = "message-native"
        result["native_terminal_outcome"] = "completed"
        opencode = collection(
            driver_kind="opencode", native_thread_ref=None,
            native_turn_ref="message-native",
        )
        observed = DriverCollectorAdapter(
            FixtureDriver(result), self.outbox,
            lambda _value: ("artifact:fixture", "d" * 64),
        ).collect(object(), "operation", opencode)
        self.assertEqual(observed.native_outcome, "completed")
        bad = dict(result, native_message_id="other")
        fresh = NodeResponseOutbox(Path(self.temp.name) / "other.sqlite")
        with self.assertRaises(BoundaryRejected):
            DriverCollectorAdapter(
                FixtureDriver(bad), fresh,
                lambda _value: ("artifact:fixture", "d" * 64),
            ).collect(object(), "operation", opencode)
        self.assertEqual(fresh.pending(), ())

    def test_each_collector_lineage_or_turn_mismatch_leaves_outbox_empty(self):
        changes = {
            "binding": {"node_id": "other", "node_boot_id": "boot", "runtime_id": "runtime",
                        "attempt_id": "attempt", "agent_slot_id": "slot", "revision": 1},
            "command_id": "other", "message_id": "other", "operation_id": "other",
            "invocation_id": "other", "attempt_id": "other", "dispatch_id": "other",
            "turn_id": "other", "thread_id": "other", "session_id": "other",
        }
        for field, changed in changes.items():
            result = dict(FixtureDriver().result)
            result[field] = changed
            with self.subTest(field=field), self.assertRaises(BoundaryRejected):
                DriverCollectorAdapter(
                    FixtureDriver(result), self.outbox,
                    lambda _value: ("artifact:fixture", "d" * 64),
                ).collect(object(), "operation", collection())
        with self.assertRaises(BoundaryRejected):
            DriverCollectorAdapter(
                FixtureDriver(), self.outbox,
                lambda _value: ("artifact:fixture", "d" * 64),
            ).collect(object(), "other-operation", collection())
        self.assertEqual(self.outbox.pending(), ())


if __name__ == "__main__":
    unittest.main()
