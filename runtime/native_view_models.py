"""Native source evidence and independent Host authorization contracts.

Only trusted server code supplies selection/caller/registration data. A verified
existing-session proof establishes a source identity, never permission to read a
transcript, watch, act, reveal, or prepare an attachment.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from runtime.receiver_contract import Capability, Contract, ReceiverBinding, ReceiverSnapshot

Reference = Annotated[str, Field(min_length=1, max_length=512)]
Revision = Annotated[int, Field(ge=0)]
HostOperation = Literal["read", "watch", "act", "reveal", "prepare_attachment"]
HOST_OPERATIONS = frozenset({"read", "watch", "act", "reveal", "prepare_attachment"})


class NativeSelection(Contract):
    """An immutable actual Core selection, not an HTTP request DTO.

    Missing runtime/Node revisions stay unknown. Selected session/generation may
    be historical; only ExistingSessionProof's verified fields assert currency.
    """

    tenant_id: Reference
    project_id: Reference
    scope_id: Reference
    agent_slot_id: Reference
    binding: ReceiverBinding
    node_id: Reference
    boot_incarnation: Reference
    node_binding_revision: Revision | None = None
    runtime_id: Reference | None = None
    runtime_binding_revision: Revision | None = None

    @model_validator(mode="after")
    def actual_address(self):
        if self.binding.actor_address != f"collaborator:{self.project_id}:{self.agent_slot_id}":
            raise ValueError("Native selection address does not match the actual project/Slot")
        if self.runtime_binding_revision is not None and self.runtime_id is None:
            raise ValueError("runtime revision requires an actual runtime identity")
        return self

    @property
    def host_ref(self) -> str:
        return self.binding.execution_host_ref


class ProviderAdmission(Contract):
    provider_ref: Reference
    native_authority: Reference
    selection: NativeSelection


class NativeSourceIdentity(Contract):
    """Actual source provenance; no URL, filesystem locator or action token."""

    provider_ref: Reference
    native_authority: Reference
    selection: NativeSelection
    host_ref: Reference
    native_session_ref: Reference
    provider_generation: Reference

    @model_validator(mode="after")
    def selected_host(self):
        if self.host_ref != self.selection.host_ref:
            raise ValueError("source Host differs from the selected execution Host")
        return self


class ExistingSessionProof(Contract):
    state: Literal["verified", "unknown", "unsupported", "disconnected"]
    reason_code: Reference | None
    provider_ref: Reference
    native_authority: Reference
    selection: NativeSelection
    host_ref: Reference
    native_session_ref: Reference | None = None
    provider_generation: Reference | None = None
    observed_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    evidence_ref: Reference | None = None
    evidence_refs: tuple[Reference, ...] = Field(default=(), max_length=32)
    intrinsic_capabilities: tuple[Capability, ...] = Field(default=(), max_length=14)
    snapshot: ReceiverSnapshot | None = None
    source: NativeSourceIdentity | None = None

    @model_validator(mode="after")
    def honest_projection(self):
        if self.host_ref != self.selection.host_ref:
            raise ValueError("proof Host differs from trusted selection")
        claimed = (self.native_session_ref, self.provider_generation, self.observed_at,
                   self.expires_at, self.evidence_ref, self.snapshot, self.source)
        if self.state != "verified":
            if any(value is not None for value in claimed) or self.intrinsic_capabilities or self.evidence_refs:
                raise ValueError("unverified proof cannot assert a current Native source")
            if self.reason_code is None:
                raise ValueError("unverified proof requires a reason")
            return self
        if any(value is None for value in claimed) or self.reason_code is not None:
            raise ValueError("verified proof requires complete source evidence")
        if self.observed_at >= self.expires_at or self.evidence_ref not in self.evidence_refs:
            raise ValueError("verified proof requires bounded evidence freshness")
        expected = NativeSourceIdentity(provider_ref=self.provider_ref, native_authority=self.native_authority,
            selection=self.selection, host_ref=self.host_ref, native_session_ref=self.native_session_ref,
            provider_generation=self.provider_generation)
        if self.source != expected:
            raise ValueError("proof source identity differs from its evidence")
        snapshot, binding = self.snapshot, self.selection.binding
        if (snapshot.receiver_id != binding.receiver_id or snapshot.address != binding.actor_address
                or snapshot.binding_epoch != binding.binding_epoch
                or snapshot.native_session_ref != self.native_session_ref
                or not snapshot.capability_scope.complete
                or snapshot.capability_scope.execution_host_ref != self.host_ref
                or snapshot.capability_scope.provider_generation != self.provider_generation
                or snapshot.capabilities != self.intrinsic_capabilities or snapshot.allowed_actions):
            raise ValueError("verified snapshot differs from selected Native source")
        for value, actual in ((binding.provider_generation, self.provider_generation),
                              (binding.native_session_ref, self.native_session_ref)):
            if value is not None and value != actual:
                raise ValueError("verified Native generation differs from trusted selection")
        axes = {o.axis: o for o in snapshot.observations}
        for axis, value in (("connection", "connected"), ("session", "present")):
            observation = axes.get(axis)
            if (observation is None or observation.knowledge != "observed"
                    or observation.source != "native_api" or observation.value != value
                    or observation.expires_at is None
                    or observation.observed_at > self.observed_at
                    or observation.expires_at < self.expires_at
                    or observation.evidence_ref not in self.evidence_refs):
                raise ValueError("verified proof requires actual Native API connection/session evidence")
        return self

    def current(self, now: datetime) -> ExistingSessionProof:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Native proof comparison requires an aware clock")
        if self.state != "verified":
            return self
        if self.observed_at <= now < self.expires_at:
            snapshot = self.snapshot.current(now, scope=self.snapshot.capability_scope)
            return self.model_copy(update={"snapshot": snapshot,
                                           "intrinsic_capabilities": snapshot.capabilities})
        return ExistingSessionProof(state="unknown", reason_code="native_proof_expired" if now >= self.expires_at
            else "native_proof_from_future", provider_ref=self.provider_ref,
            native_authority=self.native_authority, selection=self.selection, host_ref=self.host_ref)


class NativeHostCaller(Contract):
    """Trusted facade-derived caller. A principal alone is never the viewer."""

    tenant_id: Reference
    project_id: Reference
    principal_ref: Reference
    actor_address: Reference
    viewer_key: Reference
    auth_revision: Reference


class HostPermissionBinding(Contract):
    source: NativeSourceIdentity
    caller: NativeHostCaller
    operation: HostOperation
    permission_binding_nonce: Reference
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    evidence_ref: Reference

    @model_validator(mode="after")
    def bounded_scope(self):
        if self.expires_at <= self.issued_at:
            raise ValueError("Host permission expiry must follow issuance")
        if (self.caller.tenant_id, self.caller.project_id) != (
                self.source.selection.tenant_id, self.source.selection.project_id):
            raise ValueError("Host permission caller is outside the selected project")
        return self


class HostAuthorizationResult(Contract):
    state: Literal["authorized", "denied", "unsupported", "unknown"]
    reason_code: Reference | None
    permission: HostPermissionBinding | None = None

    @model_validator(mode="after")
    def explicit_result(self):
        if self.state == "authorized":
            if self.permission is None or self.reason_code is not None:
                raise ValueError("authorized Host result requires a permission binding")
        elif self.permission is not None or self.reason_code is None:
            raise ValueError("Host denial/unknown requires a reason and no permission")
        return self

    @field_validator("reason_code")
    @classmethod
    def bounded_reason(cls, value):
        if value is not None and any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Host reason contains controls")
        return value
