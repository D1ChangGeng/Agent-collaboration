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
            operation = await adapter.submit_operation(
                "test-real-temporal-operation",
                {"command_id": "cmd-real", "layer": "temporal"},
            )
        except TemporalUnavailable as exc:
            pytest.fail(f"MANDATORY_GATE_FAILURE: isolated Temporal namespace {NAMESPACE} unavailable: {exc}")
        try:
            assert operation.status == "committed"
            assert operation.workflow_id == "test-real-temporal-operation"
            assert operation.run_id
            assert (await adapter.readback(operation.operation_id))["status"] == "committed"
        except TemporalUnavailable as exc:
            pytest.fail(f"MANDATORY_GATE_FAILURE: isolated Temporal readback unavailable: {exc}")
        finally:
            await adapter.close()

    asyncio.run(scenario())
