"""Node-owned terminal response collection and projection retry."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from runtime.codex_driver import CodexAppServerDriver
from runtime.delivery_models import InvocationRequest
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.opencode_driver import OpenCodeNativeDriver
from runtime.recovery import NodeResponseOutbox, ProjectionDisposition
from runtime.recovery_models import (
    BoundaryRejected,
    DispatchIdentity,
    NativeResponseObservation,
    canonical_digest,
    response_receipt_id,
)


class NativeResponseCollector:
    """Call ``collect_result`` only, persist once, and retry only Domain projection."""

    def __init__(
        self,
        native_adapter: NativeDeliveryAdapter,
        outbox: NodeResponseOutbox,
        response_store: Callable[[dict[str, Any]], tuple[str, str]],
        project: Callable[[NativeResponseObservation], ProjectionDisposition],
    ) -> None:
        if not isinstance(native_adapter, NativeDeliveryAdapter):
            raise TypeError("a bound NativeDeliveryAdapter is required")
        if not callable(response_store) or not callable(project):
            raise TypeError("response store and Domain projector are required")
        self.native_adapter = native_adapter
        self.outbox = outbox
        self.response_store = response_store
        self.project = project

    @staticmethod
    def dispatch_identity(invocation: InvocationRequest) -> DispatchIdentity:
        envelope = invocation.envelope
        return DispatchIdentity(
            tenant_id=envelope.tenant_id,
            message_id=invocation.message_id,
            operation_id=invocation.operation_id,
            invocation_id=invocation.invocation_id,
            attempt_id=invocation.attempt_id,
            dispatch_id=invocation.dispatch_id,
            endpoint_id=envelope.endpoint_id,
            binding_revision=envelope.binding_revision,
            machine_id=envelope.machine_id,
            node_id=envelope.node_id,
            boot_incarnation=envelope.boot_incarnation,
            accepted_revision=invocation.accepted_revision,
            accepted_state_digest=invocation.accepted_state_digest,
        )

    def _collect(self, invocation: InvocationRequest) -> NativeResponseObservation:
        invocation = InvocationRequest.model_validate_json(invocation.model_dump_json(), strict=True)
        identity = self.dispatch_identity(invocation)
        cached = self.outbox.by_invocation(identity)
        if cached is not None:
            return cached
        adapter = self.native_adapter
        operation = adapter._operation(invocation)
        driver = adapter.driver
        record = driver.journal.read(invocation.invocation_id)
        if (
            record is None
            or record["action"] != "invoke"
            or record["binding_id"] != driver.binding_id
            or record["input"]["command_id"] != invocation.command_id
            or record["input"]["message_id"] != invocation.message_id
            or record["input"]["payload"].get("binding") != asdict(driver.identity)
        ):
            raise BoundaryRejected("collector invocation journal identity changed")
        result = driver.collect_result(operation, invocation.invocation_id)
        expected = {
            "receipt_layer": "response_received",
            "operation_id": invocation.invocation_id,
            "command_id": invocation.command_id,
            "message_id": invocation.message_id,
            "binding_id": driver.binding_id,
            "binding": asdict(driver.identity),
        }
        if not isinstance(result, dict) or any(result.get(key) != value for key, value in expected.items()):
            raise BoundaryRejected("Driver terminal response lineage changed")
        terminal_at = result.get("native_terminal_observed_at")
        if not isinstance(terminal_at, str):
            raise BoundaryRejected("Driver terminal timestamp is unavailable")
        try:
            observed_at = datetime.fromisoformat(terminal_at).astimezone(UTC)
        except (TypeError, ValueError):
            raise BoundaryRejected("Driver terminal timestamp is malformed") from None
        if isinstance(driver, OpenCodeNativeDriver):
            native = {
                "session_id": result.get("native_session_id"),
                "message_id": result.get("native_message_id"),
                "assistant_ids": result.get("native_assistant_ids"),
            }
            outcome = result.get("native_terminal_outcome")
        elif isinstance(driver, CodexAppServerDriver):
            native = {
                "session_id": result.get("session_id"),
                "thread_id": result.get("thread_id"),
                "turn_id": result.get("turn_id"),
            }
            outcome = result.get("native_status")
        else:
            raise BoundaryRejected("collector driver type is unsupported")
        if any(value in (None, "", []) for value in native.values()):
            raise BoundaryRejected("Driver terminal native identity is incomplete")
        if outcome not in {"completed", "failed", "interrupted"}:
            raise BoundaryRejected("Driver terminal outcome is unsupported")
        stable_result = {key: value for key, value in result.items() if key != "observed_at"}
        evidence_digest = canonical_digest(stable_result)
        response_artifact_ref, response_digest = self.response_store(stable_result)
        if not isinstance(response_artifact_ref, str) or not response_artifact_ref:
            raise BoundaryRejected("response artifact reference is unavailable")
        if response_digest != canonical_digest(stable_result):
            raise BoundaryRejected("response artifact digest differs from terminal observation")
        native_response_ref = "native-response:" + canonical_digest(native)
        projection_id = "projection:" + canonical_digest({
            "tenant_id": identity.tenant_id,
            "invocation_id": identity.invocation_id,
            "native_response_ref": native_response_ref,
        })
        observation = NativeResponseObservation(
            projection_id=projection_id,
            receipt_id=response_receipt_id(identity, projection_id),
            identity=identity,
            native_response_ref=native_response_ref,
            native_outcome=outcome,
            response_artifact_ref=response_artifact_ref,
            response_digest=response_digest,
            evidence_digest=evidence_digest,
            observed_at=observed_at,
        )
        self.outbox.record(observation)
        return observation

    def collect_and_project(self, invocation: InvocationRequest) -> ProjectionDisposition:
        observation = self._collect(invocation)
        try:
            disposition = self.project(observation)
        except Exception as error:
            self.outbox.fail(observation.projection_id, type(error).__name__)
            raise
        self.outbox.mark(disposition)
        return disposition

    def retry_pending(self, *, limit: int = 32) -> tuple[ProjectionDisposition, ...]:
        results = []
        for observation in self.outbox.pending(limit=limit):
            try:
                disposition = self.project(observation)
            except Exception as error:  # noqa: BLE001 - retain bounded retry evidence
                self.outbox.fail(observation.projection_id, type(error).__name__)
                continue
            self.outbox.mark(disposition)
            results.append(disposition)
        return tuple(results)


def artifact_response_store(store: Any) -> Callable[[dict[str, Any]], tuple[str, str]]:
    """Adapt ``LocalArtifactStore`` without exposing response bytes to command metadata."""

    def put(value: dict[str, Any]) -> tuple[str, str]:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ref = store.put_bytes(encoded, kind="readback", media_type="application/json")
        return "artifact:" + ref.sha256, ref.sha256

    return put
