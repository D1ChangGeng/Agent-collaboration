"""Purpose-bound lifecycle wire contracts over the existing pinned Receiver TLS.

Wire verification authenticates/correlates facts. Core issuance and Node current
authority remain responsible for permission. An expired execute permit alone can
never authenticate a network readback.
"""
from __future__ import annotations

import json
import secrets
from datetime import timedelta
from typing import Annotated, Literal
from uuid import uuid4

from nacl.signing import SigningKey
from pydantic import AwareDatetime, Field, model_validator

from runtime.receiver_crypto import public_key, sha256, sign, verify
from runtime.receiver_lifecycle_contract import (
    Contract,
    LifecycleSource,
    LifecycleTarget,
    SignedCapacityObservation,
    SignedLifecycleChallenge,
    SignedLifecyclePermit,
    SignedLifecycleReceipt,
    _bounded,
    _source_target,
    _window,
    verify_receipt,
)
from runtime.receiver_lifecycle_node import ReceiverLifecycleNode

OBSERVE = "/v1/lifecycle/observe"
EXECUTE = "/v1/lifecycle/execute"
READBACK = "/v1/lifecycle/readback"
PATHS = frozenset({OBSERVE, EXECUTE, READBACK})
Reference = Annotated[str, Field(min_length=1, max_length=512)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class LifecycleExecutionRequest(Contract):
    schema_version: Literal["acs-lifecycle-execution-request/1"] = "acs-lifecycle-execution-request/1"
    permit: SignedLifecyclePermit
    challenge: SignedLifecycleChallenge
    observation: SignedCapacityObservation


class LifecycleReadAdmission(Contract):
    schema_version: Literal["acs-lifecycle-read-admission/1"] = "acs-lifecycle-read-admission/1"
    purpose: Literal["receiver.lifecycle.readback"] = "receiver.lifecycle.readback"
    method: Literal["POST"] = "POST"
    path: Literal["/v1/lifecycle/readback"] = READBACK
    source: LifecycleSource
    original_target: LifecycleTarget
    execution_digest: Digest
    authority_key_id: Reference
    authority_key_revision: Annotated[int, Field(ge=1, le=2**63 - 1)]
    request_id: Reference
    nonce: Digest
    issued_at: AwareDatetime
    deadline: AwareDatetime

    @model_validator(mode="after")
    def bounded_read(self):
        _source_target(self.source, self.original_target)
        _bounded(self.issued_at, self.deadline)
        return self


class SignedLifecycleReadRequest(Contract):
    admission: LifecycleReadAdmission
    execution: LifecycleExecutionRequest
    signature: Annotated[str, Field(pattern=r"^[0-9a-f]{128}$")]


def _read_body(admission, execution):
    return {"admission": admission.model_dump(mode="json"), "execution": execution.model_dump(mode="json")}


def _same_installed(config, target):
    if (target.registration != config.binding.registration or target.node_key_id != config.binding.node_key_id
            or target.journal_generation != config.journal_generation):
        raise ValueError("lifecycle wire target differs from installed Receiver")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate lifecycle JSON member")
        result[key] = value
    return result


def parse_lifecycle(model, raw):
    value = json.loads(raw, object_pairs_hook=_unique,
                       parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    return model.model_validate_json(json.dumps(value, allow_nan=False), strict=True)


class LifecycleReceiverRouter:
    def __init__(self, config, node: ReceiverLifecycleNode):
        if not isinstance(node, ReceiverLifecycleNode):
            raise TypeError("an actual current-authority Node lifecycle controller is required")
        if (node.config.binding != config.binding or node.config.authority_key_id != config.authority_key_id
                or node.config.authority_key_revision != config.authority_key_revision
                or node.config.authority_public_key != config.authority_public_key
                or node.config.journal_generation != config.journal_generation):
            raise ValueError("lifecycle controller and Receiver trust differ")
        self.config, self.node = config, node

    def handle(self, path, raw):
        if len(raw) > self.config.maximum_body_bytes or path not in PATHS:
            raise ValueError("lifecycle wire request rejected")
        if path == OBSERVE:
            return self.node.observe(parse_lifecycle(SignedLifecycleChallenge, raw))
        if path == EXECUTE:
            request = parse_lifecycle(LifecycleExecutionRequest, raw)
            return self.node.execute(request.permit, challenge=request.challenge, observation=request.observation)
        request = parse_lifecycle(SignedLifecycleReadRequest, raw)
        admission, execution = request.admission, request.execution
        plan = execution.permit.permit.plan
        if ((admission.source, admission.original_target, admission.execution_digest,
                admission.authority_key_id, admission.authority_key_revision) !=
               (plan.source, plan.target, sha256(execution), self.config.authority_key_id, self.config.authority_key_revision)):
            raise ValueError("lifecycle readback correlation rejected")
        _same_installed(self.config, admission.original_target)
        verify(self.config.authority_public_key, request.signature, _read_body(admission, execution))
        _window(self.node.clock, plan.target, admission.issued_at, admission.deadline)
        # The Node's separate original-scope current read hook remains mandatory.
        receipt = self.node.reconcile(execution.permit, challenge=execution.challenge, observation=execution.observation)
        _window(self.node.clock, plan.target, admission.issued_at, admission.deadline)
        return receipt


class RemoteLifecycleTransport:
    """Runtime-installed adapter; no backend/key/locator is accepted on the wire."""
    def __init__(self, remote, signing_key: SigningKey):
        from runtime.remote_endpoint import RemoteNodeTransport

        if not isinstance(remote, RemoteNodeTransport) or type(signing_key) is not SigningKey:
            raise TypeError("existing pinned Receiver transport and installed Authority key required")
        if public_key(signing_key) != remote.config.authority_public_key:
            raise ValueError("lifecycle Authority key differs from installed Receiver")
        self.remote, self.config, self.signing_key = remote, remote.config, signing_key

    def _observation(self, challenge, signed):
        observed, expected = signed.observation, challenge.challenge
        if ((observed.challenge_digest, observed.request_id, observed.nonce, observed.source_digest,
                observed.target, observed.node_key_id) !=
               (sha256(expected), expected.request_id, expected.nonce, sha256(expected.source), expected.target, expected.target.node_key_id)):
            raise ValueError("lifecycle Node observation correlation rejected")
        verify(self.config.binding.node_public_key, signed.signature, observed)
        _window(self.remote.clock, expected.target, expected.issued_at, expected.deadline)
        _window(self.remote.clock, expected.target, observed.capacity.observed_at, observed.capacity.valid_until)
        return signed

    def observe(self, challenge):
        challenge = SignedLifecycleChallenge.model_validate_json(challenge.model_dump_json(), strict=True)
        _same_installed(self.config, challenge.challenge.target)
        raw = self.remote.exchange_lifecycle(OBSERVE, challenge.model_dump_json().encode(), challenge.challenge.deadline)
        return self._observation(challenge, parse_lifecycle(SignedCapacityObservation, raw))

    def _result(self, execution, raw):
        signed = parse_lifecycle(SignedLifecycleReceipt, raw)
        plan = execution.permit.permit.plan

        def correlate(_stage, source, target):
            self.remote._assert_peer()
            _same_installed(self.config, target)
            if source != plan.source or target != plan.target:
                raise ValueError("lifecycle result subject rejected")

        # This is transport correlation, not a Domain permission grant. The
        # Core executor validates its actual locked original operation again.
        verify_receipt(signed, permit=execution.permit.permit, expected_source=plan.source,
            actual_target=plan.target, node_public_key=self.config.binding.node_public_key,
            clock=self.remote.clock, authorize_current=correlate)
        return signed

    def execute(self, permit, *, challenge, observation):
        execution = LifecycleExecutionRequest(permit=permit, challenge=challenge, observation=observation)
        _same_installed(self.config, permit.permit.plan.target)
        raw = self.remote.exchange_lifecycle(EXECUTE, execution.model_dump_json().encode(), permit.permit.deadline)
        return self._result(execution, raw)

    def readback(self, permit, *, challenge, observation):
        execution = LifecycleExecutionRequest(permit=permit, challenge=challenge, observation=observation)
        _same_installed(self.config, permit.permit.plan.target)
        now = self.remote.clock.observation_time()
        admission = LifecycleReadAdmission(source=permit.permit.plan.source, original_target=permit.permit.plan.target,
            execution_digest=sha256(execution), authority_key_id=self.config.authority_key_id,
            authority_key_revision=self.config.authority_key_revision, request_id="lifecycle-read-" + uuid4().hex,
            nonce=secrets.token_hex(32), issued_at=now, deadline=now + timedelta(seconds=10))
        signed = SignedLifecycleReadRequest(admission=admission, execution=execution,
            signature=sign(self.signing_key, _read_body(admission, execution)))
        raw = self.remote.exchange_lifecycle(READBACK, signed.model_dump_json().encode(), admission.deadline)
        return self._result(execution, raw)


class ConfiguredLifecycleTransport:
    """Refresh trusted sender settings/registration without automatic preparation."""
    def __init__(self, endpoint):
        from runtime.machine_connections import ConfiguredRemoteEndpoint

        if not isinstance(endpoint, ConfiguredRemoteEndpoint):
            raise TypeError("a Runtime-configured Receiver connection is required")
        self.endpoint = endpoint

    def _current(self):
        with self.endpoint._lock:
            self.endpoint._refresh_settings()
            if not self.endpoint.settings.lifecycle_control:
                raise ValueError("configured lifecycle transport was disabled")
            adapter = self.endpoint._adapter()
            # _adapter refreshes the file again; disabling during that refresh
            # must not leave a newly admitted lifecycle handle behind.
            if not self.endpoint.settings.lifecycle_control:
                raise ValueError("configured lifecycle transport was disabled")
            return RemoteLifecycleTransport(adapter.transport, adapter._signing_key)

    @property
    def config(self):
        return self._current().config

    @property
    def signing_key(self):
        return self._current().signing_key

    def observe(self, challenge):
        return self._current().observe(challenge)

    def execute(self, permit, *, challenge, observation):
        return self._current().execute(permit, challenge=challenge, observation=observation)

    def readback(self, permit, *, challenge, observation):
        return self._current().readback(permit, challenge=challenge, observation=observation)
