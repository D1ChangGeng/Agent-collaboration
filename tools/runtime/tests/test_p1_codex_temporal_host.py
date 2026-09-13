"""One actual Temporal Workflow/Run dispatched through the fixed host Node path."""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from temporalio.client import Client

from runtime.p1_codex_host_node import CodexHostNodeEndpoint
from runtime_tests.test_delivery import query
from runtime_tests.test_p1_codex_host_node import _host, _send
from tools.runtime.p1_codex_host_scene import TemporalHostDispatcher

pytest_plugins = ("runtime_tests.test_delivery",)


def test_original_temporal_run_uses_restricted_host_dispatch_once(setup, tmp_path):
    if not sys.platform.startswith("linux") or os.geteuid() == 0:
        pytest.skip("real PG, Temporal and POSIX host Node required")
    endpoint = os.getenv("ACS_P1_TEMPORAL_ENDPOINT")
    namespace = os.getenv("ACS_P1_TEMPORAL_NAMESPACE")
    if endpoint != "127.0.0.1:7239" or not namespace:
        pytest.skip("reviewed local Temporal target is unavailable")
    initial, native, config, private = _host(setup, tmp_path)
    request = _send(setup, initial.policy)
    temporal = TemporalHostDispatcher(
        initial.dispatcher,
        endpoint=endpoint,
        namespace=namespace,
        task_queue="p1-host-" + initial.policy.run_id,
        deadline=initial.policy.deadline,
    )
    host = CodexHostNodeEndpoint(
        initial.policy,
        temporal,
        private / "runs.sqlite",
        native_path=native,
        config_path=config,
        fixture_mode=True,
    )
    first = host.handle(request)
    assert first.status == "delivered"
    assert first.attempt_id and first.dispatch_id
    assert temporal.last is not None
    workflow_id = "acs-delivery/" + request.operation_id
    assert temporal.last["workflow_id"] == workflow_id
    assert temporal.last["provider_run_id"]
    assert query(
        setup,
        "SELECT provider_workflow_id,provider_run_id FROM operations WHERE operation_id=%s",
        (request.operation_id,),
    ) == [(workflow_id, temporal.last["provider_run_id"])]

    async def read_original():
        client = await Client.connect(endpoint, namespace=namespace)
        handle = client.get_workflow_handle(workflow_id, run_id=temporal.last["provider_run_id"])
        return await handle.result()

    assert asyncio.run(read_original())["status"] == "delivered"
    assert host.handle(request.model_copy(update={"action": "readback"})) == first
    assert host.handle(request).status == "delivered"
    assert setup.driver.calls == [request.operation_id]
    assert query(setup, "SELECT count(*) FROM delivery_attempts") == [(1,)]
