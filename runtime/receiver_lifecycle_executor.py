"""Recovery lifecycle orchestration with commit-before-Host boundaries.

The transport is installed by trusted Runtime code. This module never selects a
backend from a caller body or falls back to an unfenced prepare_runtime callback.
It reuses the accepted recovery operation and outbox; there is no new ledger.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from nacl.signing import SigningKey
from psycopg.pq import TransactionStatus

from runtime.connection_clock import ConnectionClock
from runtime.errors import AuthorizationDenied
from runtime.receiver_config import ReceiverClientConfig, receiver_clock_identity
from runtime.receiver_crypto import public_key, sha256
from runtime.receiver_lifecycle_contract import (
    LifecycleContractRejected,
    SignedCapacityObservation,
    SignedLifecycleChallenge,
    SignedLifecyclePermit,
    SignedLifecycleReceipt,
    verify_receipt,
)
from runtime.receiver_lifecycle_issuance import (
    LifecycleIssuance,
    LifecycleIssuanceRejected,
    _possible,
    _state,
)
from runtime.receiver_lifecycle_readback import require_original_lifecycle_read
from runtime.receiver_recovery_operations import FINAL, RecoveryRequest


class LifecycleTransport(Protocol):
    config: ReceiverClientConfig
    signing_key: SigningKey

    def observe(self, challenge: SignedLifecycleChallenge) -> SignedCapacityObservation: ...
    def execute(self, permit: SignedLifecyclePermit, *, challenge: SignedLifecycleChallenge,
                observation: SignedCapacityObservation) -> SignedLifecycleReceipt: ...
    def readback(self, permit: SignedLifecyclePermit, *, challenge: SignedLifecycleChallenge,
                 observation: SignedCapacityObservation) -> SignedLifecycleReceipt: ...


@dataclass(frozen=True)
class InProcessLifecycleTransport:
    """Explicit Node-owned in-process adapter; no delivery Driver fallback."""
    node: object
    signing_key: SigningKey

    @property
    def config(self):
        return self.node.config

    def observe(self, challenge):
        return self.node.observe(challenge)

    def execute(self, permit, *, challenge, observation):
        return self.node.execute(permit, challenge=challenge, observation=observation)

    def readback(self, permit, *, challenge, observation):
        # This is a trusted programmatic call. A network adapter must provide
        # fresh authenticated readback-purpose admission, not replay an expired
        # mutation permit as its caller authentication.
        return self.node.reconcile(permit, challenge=challenge, observation=observation)


class LifecycleExecutorRejected(ValueError):
    pass


class ReceiverLifecycleExecutor:
    def __init__(self, recovery, transport: LifecycleTransport):
        config = transport.config
        if (not isinstance(config, ReceiverClientConfig) or type(transport.signing_key) is not SigningKey
                or public_key(transport.signing_key) != config.authority_public_key
                or any(not callable(getattr(transport, name, None)) for name in ("observe", "execute", "readback"))):
            raise LifecycleExecutorRejected("installed lifecycle transport and actual Authority key required")
        config.validate()
        self.recovery, self.transport = recovery, transport
        self.authority = recovery.authority
        self.config = config
        self._transport_identity = sha256(config.binding.model_dump(mode="json"))
        self.issuer = LifecycleIssuance(recovery, transport.signing_key, journal_generation=config.journal_generation)

    def _caller(self, cursor, authority, project, operation_ref, credential):
        from runtime.receiver_rebind import lifecycle_receiver

        self.recovery.projects.service.authenticate(credential)
        payload = self.recovery._row(cursor, project, operation_ref, lock=True)
        request = RecoveryRequest.model_validate(payload["request"])
        _bound, _cmd, _endpoint, actor, _message = self.recovery._authorize(
            cursor, authority, project, payload["receiver_id"], request, lock_endpoint=False)
        if actor != payload["actor"]:
            raise AuthorizationDenied(self.recovery.projects.context.principal_ref,
                                      self.recovery.projects.context.grant_ref)
        if (request.action not in {"prepare_receiver", "resume_receiver", "rebind_receiver"}
                or lifecycle_receiver(payload)[0] != self.config.binding.registration.endpoint_id):
            raise LifecycleExecutorRejected("original lifecycle action or configured receiver differs")
        return payload

    def _host_boundary(self):
        borrowed = getattr(self.authority, "_transaction_connection", None)
        if borrowed is not None and not borrowed.closed and borrowed.info.transaction_status == TransactionStatus.INTRANS:
            raise LifecycleExecutorRejected("Host I/O requires a committed Core phase")
        if (self.transport.config != self.config
                or sha256(self.transport.config.binding.model_dump(mode="json")) != self._transport_identity
                or public_key(self.transport.signing_key) != self.config.authority_public_key):
            raise LifecycleExecutorRejected("installed lifecycle transport changed")

    def _operation(self, project, operation_ref, credential):
        # This fresh current-caller read occurs after recording technical facts.
        # Losing caller authority cannot erase an authentic Native result.
        return self.recovery.read(project, operation_ref, credential)

    def _failure(self, project, operation_ref, reason, *, possible):
        with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            payload = self.recovery._row(cursor, project, operation_ref, lock=True)
            old = payload["operation"]
            if old["state"] in FINAL and old["state"] != "unknown":
                return
            already = old.get("effect_state") in {"native_possible", "unknown"}
            operation = old | {"state": "unknown" if possible or already else "deferred",
                "effect_state": "native_possible" if possible or already else "committed", "reason_code": reason,
                "revision": old["revision"] + 1, "updated_at": authority.canonical_now(cursor).isoformat()}
            self.recovery._save(cursor, payload, operation, done=possible or already)

    def _receipt(self, project, operation_ref, signed):
        signed = SignedLifecycleReceipt.model_validate_json(signed.model_dump_json(), strict=True)
        with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            payload = self.recovery._row(cursor, project, operation_ref, lock=True)
            data = deepcopy(payload.get("lifecycle"))
            if not isinstance(data, dict) or data.get("phase") != "executing":
                raise LifecycleExecutorRejected("original possible-effect phase is unavailable")
            permit = SignedLifecyclePermit.model_validate_json(json.dumps(data["permit"]), strict=True)
            if (data.get("permit_digest") != sha256(permit.permit)
                    or data.get("first_plan_digest") != permit.permit.semantic_digest):
                raise LifecycleExecutorRejected("original lifecycle permit changed")

            def stored_fact(_stage, source, target):
                # Permission to execute was committed before the Host call.
                # Recording its authenticated result is not another admission.
                current = self.recovery._row(cursor, project, operation_ref, lock=True)
                saved = current.get("lifecycle", {})
                if (saved.get("permit") != data["permit"] or saved.get("permit_digest") != data["permit_digest"]
                        or source != permit.permit.plan.source or target != permit.permit.plan.target):
                    raise LifecycleExecutorRejected("original lifecycle result lost its immutable subject")

            clock = ConnectionClock("lifecycle-result:" + operation_ref,
                lambda: authority.canonical_now(cursor), identity=receiver_clock_identity(self.config))
            receipt = verify_receipt(signed, permit=permit.permit, expected_source=permit.permit.plan.source,
                actual_target=permit.permit.plan.target, node_public_key=self.config.binding.node_public_key,
                clock=clock, authorize_current=stored_fact)
            previous = data.get("receipt")
            if previous is not None:
                old_receipt = SignedLifecycleReceipt.model_validate_json(json.dumps(previous), strict=True)
                if old_receipt.receipt.outcome == "acknowledged":
                    return  # An unknown/later observation cannot erase positive original evidence.
            data["receipt"] = signed.model_dump(mode="json")
            if receipt.outcome == "acknowledged":
                state, effect, reason, data["phase"] = "completed", "native_possible", None, "settled"
            elif receipt.outcome == "definitively_not_started":
                state, effect, reason, data["phase"] = "definitively_rejected", "committed", receipt.reason_code, "settled"
            else:
                state, effect, reason = "unknown", "native_possible", receipt.reason_code
            old = payload["operation"]
            operation = old | {"state": state, "effect_state": effect, "reason_code": reason,
                "revision": old["revision"] + 1, "updated_at": authority.canonical_now(cursor).isoformat(),
                "evidence_refs": list(dict.fromkeys([*old["evidence_refs"], "lifecycle-receipt:" + sha256(receipt)]))}
            self.recovery._save(cursor, payload | {"lifecycle": data}, operation, done=True)

    def advance(self, project, operation_ref, credential):
        with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
            payload = self._caller(cursor, authority, project, operation_ref, credential)
            if payload["operation"]["state"] in FINAL and payload["operation"]["state"] != "unknown":
                return payload["operation"]
            data = _state(payload)
            if _possible(payload, data):
                if data is None or data.get("permit") is None:
                    raise LifecycleExecutorRejected("original possible-effect lifecycle artifacts are unavailable")
                permit = SignedLifecyclePermit.model_validate_json(json.dumps(data["permit"]), strict=True)
                challenge = SignedLifecycleChallenge.model_validate_json(json.dumps(data["challenge"]), strict=True)
                observation = SignedCapacityObservation.model_validate_json(json.dumps(data["observation"]), strict=True)
                # Reading original facts requires current original-scope READ,
                # not renewed authority to execute the past action again.
                require_original_lifecycle_read(self.recovery, cursor, permit)
            else:
                result = self.issuer.issue_challenge(cursor, project, operation_ref)
                if result.kind == "settled":
                    return result.operation
                if result.kind != "challenge":
                    raise LifecycleExecutorRejected("lifecycle phase changed before original admission")
                challenge = result.challenge
                permit = observation = None
        # The outer transaction committed, not merely an inner savepoint.
        self._host_boundary()
        if permit is not None:
            try:
                signed = self.transport.readback(permit, challenge=challenge, observation=observation)
                self._receipt(project, operation_ref, signed)
            except Exception:  # noqa: BLE001 - readback never authorizes replay.
                self._failure(project, operation_ref, "lifecycle_original_readback_unavailable", possible=True)
            return self._operation(project, operation_ref, credential)
        try:
            observed = self.transport.observe(challenge)
        except Exception:  # noqa: BLE001 - observation purpose has no Native effect.
            self._failure(project, operation_ref, "lifecycle_capacity_transport_unavailable", possible=False)
            return self._operation(project, operation_ref, credential)
        try:
            with self.authority.transaction() as (authority, connection), connection.cursor() as cursor:
                self._caller(cursor, authority, project, operation_ref, credential)
                result = self.issuer.record_observation(cursor, project, operation_ref, observed)
                if result.kind == "rebind_ready":
                    from runtime.receiver_rebind import publish_rebind

                    return publish_rebind(self.recovery, cursor, project, operation_ref,
                        journal_generation=self.config.journal_generation)
                if result.kind != "planned":
                    return result.operation
                result = self.issuer.issue_permit(cursor, project, operation_ref)
                permit = result.permit
        except (LifecycleContractRejected, LifecycleIssuanceRejected):
            # The entire pre-effect parent rolled back. Expired/changed facts
            # keep an observable original operation rather than escaping as a
            # generic failure or authorizing another command/Native session.
            self._failure(project, operation_ref, "lifecycle_admission_unavailable", possible=False)
            return self._operation(project, operation_ref, credential)
        self._host_boundary()
        try:
            signed = self.transport.execute(permit, challenge=challenge, observation=observed)
            self._receipt(project, operation_ref, signed)
        except Exception:  # noqa: BLE001 - possible input is never retried after transport failure.
            self._failure(project, operation_ref, "lifecycle_execution_transport_unavailable", possible=True)
        return self._operation(project, operation_ref, credential)
