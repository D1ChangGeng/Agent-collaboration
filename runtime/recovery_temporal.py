"""Temporal retries for committed projection and Human Bridge provider effects."""
from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="AcsResponseProjectionRetry")
class ResponseProjectionWorkflow:
    def __init__(self) -> None:
        self._state = {"status": "scheduled"}

    @workflow.run
    async def run(self, identity: dict) -> dict:
        for _ in range(64):
            self._state = await workflow.execute_activity(
                "acs-response-projection-retry",
                identity,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if self._state["status"] in {"applied", "fenced_late", "empty"}:
                return self._state
            await workflow.sleep(timedelta(seconds=1))
        return {"status": "retry_budget_exhausted", "identity": identity}

    @workflow.query(name="state")
    def state(self) -> dict:
        return dict(self._state)


@workflow.defn(name="AcsHumanBridgeProviderEffect")
class HumanBridgeProviderWorkflow:
    @workflow.run
    async def run(self, identity: dict) -> dict:
        return await workflow.execute_activity(
            "acs-human-bridge-provider-effect",
            identity,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=8),
        )


@workflow.defn(name="AcsRecoveryIncidentTimer")
class RecoveryIncidentTimerWorkflow:
    @workflow.run
    async def run(self, identity: dict) -> dict:
        await workflow.sleep(timedelta(seconds=identity["delay_seconds"]))
        return await workflow.execute_activity(
            "acs-recovery-incident-expire",
            identity,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=8),
        )


class RecoveryActivities:
    def __init__(self, response_collector=None, provider_dispatcher=None, incident_expirer=None):
        self.response_collector = response_collector
        self.provider_dispatcher = provider_dispatcher
        self.incident_expirer = incident_expirer

    @activity.defn(name="acs-response-projection-retry")
    async def project(self, identity: dict) -> dict:
        if self.response_collector is None:
            return {"status": "empty", "identity": identity}
        results = await asyncio.to_thread(self.response_collector.retry_pending, limit=128)
        match = next((item for item in results if item.projection_id == identity["projection_id"]), None)
        return {"status": match.disposition if match else "retry_wait", "identity": identity}

    @activity.defn(name="acs-human-bridge-provider-effect")
    async def provider(self, identity: dict) -> dict:
        if self.provider_dispatcher is None:
            raise RuntimeError("Human Bridge provider dispatcher is unavailable")
        return await asyncio.to_thread(self.provider_dispatcher, identity)

    @activity.defn(name="acs-recovery-incident-expire")
    async def expire(self, identity: dict) -> dict:
        if self.incident_expirer is None:
            raise RuntimeError("recovery incident expiry dispatcher is unavailable")
        return await asyncio.to_thread(self.incident_expirer, identity)
