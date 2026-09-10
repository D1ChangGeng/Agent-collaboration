from __future__ import annotations

import asyncio
import os

import pytest

from runtime.temporal import TEMPORAL_SDK_AVAILABLE, TemporalAdapter, TemporalUnavailable

ENDPOINT = os.getenv("ACS_P1_TEMPORAL_ENDPOINT", "")
NAMESPACE = os.getenv("ACS_P1_TEMPORAL_NAMESPACE", "")


def test_temporal_unavailable_fails_closed_when_endpoint_missing() -> None:
    async def scenario() -> None:
        adapter = TemporalAdapter(endpoint="127.0.0.1:1")
        with pytest.raises(TemporalUnavailable):
            await adapter.connect()
        assert adapter._client is None

    asyncio.run(scenario())


def test_real_temporal_submit_and_query_when_endpoint_is_available() -> None:
    async def scenario() -> None:
        if not TEMPORAL_SDK_AVAILABLE:
            pytest.skip("NOT_RUN_UNIT: temporalio SDK is unavailable")
        if not ENDPOINT or not NAMESPACE:
            pytest.skip("NOT_RUN_GATE: set ACS_P1_TEMPORAL_ENDPOINT and ACS_P1_TEMPORAL_NAMESPACE to the isolated acs-p1 profile")
        adapter = TemporalAdapter(endpoint=ENDPOINT, namespace=NAMESPACE)
        try:
            await adapter.connect()
        except TemporalUnavailable as exc:
            pytest.fail(f"MANDATORY_GATE_FAILURE: isolated Temporal endpoint {ENDPOINT}/{NAMESPACE} unavailable: {exc}")
        try:
            payload = {"command_id": "cmd-real", "tenant_id": "tenant-real", "lineage": "lineage-real", "layer": "temporal"}
            operation = await adapter.submit_operation(f"test-real-temporal-operation-{os.getpid()}", payload)
        except TemporalUnavailable as exc:
            pytest.fail(f"MANDATORY_GATE_FAILURE: isolated Temporal namespace {NAMESPACE} unavailable: {exc}")
        try:
            assert operation.status == "committed"
            assert operation.workflow_id.startswith("test-real-temporal-operation-")
            assert operation.run_id
            assert (await adapter.readback(operation.operation_id))["status"] == "committed"
            replay = await adapter.submit_operation(operation.operation_id, dict(reversed(tuple(payload.items()))))
            assert replay.run_id == operation.run_id
            assert replay.result == operation.result
            with pytest.raises(TemporalUnavailable, match="conflicts"):
                await adapter.submit_operation(operation.operation_id, {**payload, "lineage": "changed"})
        except TemporalUnavailable as exc:
            pytest.fail(f"MANDATORY_GATE_FAILURE: isolated Temporal readback unavailable: {exc}")
        finally:
            await adapter.close()

    asyncio.run(scenario())


def test_temporal_replay_survives_new_adapter_instance() -> None:
    async def scenario() -> None:
        if not TEMPORAL_SDK_AVAILABLE:
            pytest.skip("NOT_RUN_UNIT: temporalio SDK is unavailable")
        if not ENDPOINT or not NAMESPACE:
            pytest.skip("NOT_RUN_GATE: set ACS_P1_TEMPORAL_ENDPOINT and ACS_P1_TEMPORAL_NAMESPACE to the isolated acs-p1 profile")
        operation_id = f"test-temporal-adapter-restart-{os.getpid()}"
        payload = {"command_id": "cmd-restart", "tenant_id": "tenant-restart", "lineage": "lineage-restart"}
        first = TemporalAdapter(endpoint=ENDPOINT, namespace=NAMESPACE)
        try:
            await first.connect()
            original = await first.submit_operation(operation_id, payload)
        finally:
            await first.close()
        second = TemporalAdapter(endpoint=ENDPOINT, namespace=NAMESPACE)
        try:
            await second.connect(start_worker=False)
            replay = await second.submit_operation(operation_id, payload)
            assert replay.run_id == original.run_id
            assert replay.result == original.result
            assert (await second.readback(operation_id))["status"] == "committed"
        finally:
            await second.close()

    asyncio.run(scenario())
