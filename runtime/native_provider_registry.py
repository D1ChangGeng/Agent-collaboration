"""Server-admitted Native source providers, with no implicit Host permissions.

Registry admission is operator/server composition, never auto-registration from
an HTTP body, provider brand, URL or credential. Local proof uses the configured
Node readback path. Original provenance uses one configured local DriverJournal
or authenticated remote Receiver reader, independently of Host permissions.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Protocol
from weakref import WeakKeyDictionary

from runtime.codex_driver import DriverJournal
from runtime.delivery_node import DeliveryBoundaryRejected, LocalNodeEndpoint
from runtime.native_delivery import NativeDeliveryAdapter
from runtime.native_view_models import (
    HOST_OPERATIONS,
    ExistingSessionProof,
    HostAuthorizationResult,
    HostOperation,
    NativeHostCaller,
    NativeSelection,
    NativeSourceIdentity,
    ProviderAdmission,
)
from runtime.receiver_contract import ReceiverSnapshot


class NativeProviderRejected(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class NativeRegistrationFence:
    """Opaque process-local registration identity, never a Host capability.

    Only resolve_fenced() admits an instance into its owning registry. This
    object carries no serializable source, permission, token or generation.
    """

    __slots__ = ("__weakref__",)


class ExistingSessionProofPort(Protocol):
    """An independently admitted Host extension; observation only."""

    def existing_session(self, selection: NativeSelection) -> ReceiverSnapshot: ...


class NativeHostAuthorizationPort(Protocol):
    """Independent current Host permission check; does not perform the action.

    Implementations own Host authentication and nonce validation. Future action
    ports must recheck the permission nonce, generation and expiry at effects.
    """

    def authorize(self, caller: NativeHostCaller, source: NativeSourceIdentity,
                  operation: HostOperation) -> HostAuthorizationResult: ...


def _clock(clock: Callable[[], datetime]) -> datetime:
    now = clock()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Native registry requires an aware trusted clock")
    return now


class LocalExistingSessionProvider:
    """Observe an actual LocalNodeEndpoint; never start or prepare its driver."""

    def __init__(self, endpoint: LocalNodeEndpoint):
        if not isinstance(endpoint, LocalNodeEndpoint):
            raise TypeError("an actual configured LocalNodeEndpoint is required")
        self.endpoint = endpoint

    def existing_session(self, selection: NativeSelection) -> ReceiverSnapshot:
        expected = {"machine_id": selection.host_ref, "node_id": selection.node_id,
            "boot_incarnation": selection.boot_incarnation, "scope_id": selection.scope_id,
            "agent_slot_id": selection.agent_slot_id}
        before = self.endpoint.descriptor()
        if not isinstance(before, dict) or any(before.get(key) != value for key, value in expected.items()):
            raise NativeProviderRejected("native_endpoint_selection_changed")
        if not isinstance(self.endpoint.driver, NativeDeliveryAdapter):
            from runtime.receiver_evidence import unknown_receiver

            return unknown_receiver(selection.binding, reason="native_adapter_contract_unavailable")
        snapshot = self.endpoint.receiver_snapshot(selection.binding)
        after = self.endpoint.descriptor()
        if before != after or any(after.get(key) != value for key, value in expected.items()):
            raise NativeProviderRejected("native_endpoint_changed_during_readback")
        return snapshot


@dataclass(frozen=True)
class _RegisteredProvider:
    admission: ProviderAdmission
    proof_port: ExistingSessionProofPort | None
    authorization_port: NativeHostAuthorizationPort | None
    source_journal: DriverJournal | None = None
    source_reader: object | None = None


class NativeProviderRegistry:
    def __init__(self, *, clock: Callable[[], datetime] | None = None, proof_ttl_seconds: float = 5):
        if (isinstance(proof_ttl_seconds, bool) or not isinstance(proof_ttl_seconds, (int, float))
                or not 0 < proof_ttl_seconds <= 30):
            raise ValueError("Native proof TTL must be positive and at most 30 seconds")
        self.clock = clock or (lambda: datetime.now(UTC))
        self.proof_ttl = timedelta(seconds=proof_ttl_seconds)
        self._lock = RLock()
        self._providers: dict[tuple[str, str], _RegisteredProvider] = {}
        self._fences: WeakKeyDictionary[NativeRegistrationFence, tuple[tuple[str, str], _RegisteredProvider]] = WeakKeyDictionary()

    def register(self, admission: ProviderAdmission, provider: ExistingSessionProofPort | None, *,
                 authorization_port: NativeHostAuthorizationPort | None = None,
                 source_journal: DriverJournal | None = None, source_reader=None) -> None:
        """Trusted composition only. Replacement needs explicit unregister first."""
        from runtime.remote_native_source import RemoteNativeSourceReader

        if source_reader is not None and not isinstance(source_reader, RemoteNativeSourceReader):
            raise TypeError("remote Native provenance requires a trusted authenticated Receiver reader")
        if source_reader is not None and source_journal is not None:
            raise TypeError("an original source has one configured reader")
        if type(admission) is not ProviderAdmission:
            raise TypeError("a typed server ProviderAdmission is required")
        admission = ProviderAdmission.model_validate_json(admission.model_dump_json())
        if provider is not None and not callable(getattr(provider, "existing_session", None)):
            raise TypeError("provider requires an admitted existing-session proof port")
        if authorization_port is not None and not callable(getattr(authorization_port, "authorize", None)):
            raise TypeError("Host authorization requires an independent authorization port")
        if source_journal is None and source_reader is None and isinstance(provider, LocalExistingSessionProvider):
            adapter = provider.endpoint.driver
            if isinstance(adapter, NativeDeliveryAdapter):
                source_journal = adapter.driver.journal
        if source_journal is not None and not isinstance(source_journal, DriverJournal):
            raise TypeError("Native provenance requires an actual trusted DriverJournal")
        key = admission.provider_ref, admission.native_authority
        with self._lock:
            if key in self._providers:
                raise NativeProviderRejected("native_provider_already_registered")
            self._providers[key] = _RegisteredProvider(admission, provider, authorization_port, source_journal, source_reader)

    def original_source(self, selection: NativeSelection):
        """Select one original server admission, without Host proof or I/O.

        No provider name, NativeLink, session replacement or path comes from the
        reader. An ambiguous original binding is unavailable, never guessed.
        """
        with self._lock:
            matches = []
            for key, registered in self._providers.items():
                if ((registered.source_journal is None and registered.source_reader is None)
                        or registered.admission.native_authority not in {"orca", "harness"}):
                    continue
                try:
                    admission = self.resolve(*key, selection)
                except NativeProviderRejected:
                    continue
                matches.append((key, admission, registered.source_reader or registered.source_journal))
            if len(matches) != 1:
                raise NativeProviderRejected("native_source_provider_ambiguous" if matches else "native_source_provider_unavailable")
            key, _admission, journal = matches[0]
            admission, fence = self.resolve_fenced(*key, selection)
            return admission, journal, fence

    def unregister(self, provider_ref: str, native_authority: str) -> None:
        with self._lock:
            self._providers.pop((provider_ref, native_authority), None)

    def resolve(self, provider_ref: str, native_authority: str,
                actual_selection: NativeSelection) -> ProviderAdmission:
        """Resolve unknown optional Core fields from existing server admission.

        This is a metadata lookup, not a proof, permission, registration refresh
        or session discovery. Every mandatory field and every known optional Core
        value must agree. Later prove() still requires exact selection equality
        and fresh Host evidence; replacement/rebind can invalidate this result.
        """
        if type(actual_selection) is not NativeSelection:
            raise TypeError("an actual typed Core NativeSelection is required")
        try:
            actual = NativeSelection.model_validate_json(actual_selection.model_dump_json())
        except (TypeError, ValueError) as error:
            raise NativeProviderRejected("native_provider_selection_invalid") from error
        with self._lock:
            registered = self._providers.get((provider_ref, native_authority))
            if registered is None:
                raise NativeProviderRejected("native_provider_not_registered")
            try:
                admission = ProviderAdmission.model_validate_json(registered.admission.model_dump_json())
            except (TypeError, ValueError) as error:
                raise NativeProviderRejected("native_provider_admission_invalid") from error
            if (admission.provider_ref, admission.native_authority) != (provider_ref, native_authority):
                raise NativeProviderRejected("native_provider_admission_invalid")
            actual_fields = actual.model_dump(mode="python")
            registered_fields = admission.selection.model_dump(mode="python")
            known_optional_conflict = False
            for field in ("node_binding_revision", "runtime_id", "runtime_binding_revision"):
                supplied, admitted = actual_fields.pop(field), registered_fields.pop(field)
                known_optional_conflict |= supplied is not None and supplied != admitted
            for field in ("provider_generation", "native_session_ref"):
                supplied = actual_fields["binding"].pop(field)
                admitted = registered_fields["binding"].pop(field)
                known_optional_conflict |= supplied is not None and supplied != admitted
            if actual_fields != registered_fields:
                raise NativeProviderRejected("native_provider_selection_changed")
            if known_optional_conflict:
                raise NativeProviderRejected("native_provider_optional_selection_changed")
            return admission

    def resolve_fenced(self, provider_ref: str, native_authority: str,
                       actual_selection: NativeSelection) -> tuple[ProviderAdmission, NativeRegistrationFence]:
        """Atomically resolve metadata and capture this registration incarnation.

        Call assert_current() in final Core admission, including after SQL lock
        waits/storage work while that transaction can still roll back. A fence
        neither extends a proof's TTL nor grants any Host read/action permission.
        """
        with self._lock:
            admission = self.resolve(provider_ref, native_authority, actual_selection)
            key = provider_ref, native_authority
            fence = NativeRegistrationFence()
            self._fences[fence] = key, self._providers[key]
            return admission, fence

    def assert_current(self, fence: NativeRegistrationFence) -> None:
        """Pure metadata check; replacement invalidates even equal admission."""
        with self._lock:
            if type(fence) is not NativeRegistrationFence:
                raise NativeProviderRejected("native_provider_fence_invalid")
            owned = self._fences.get(fence)
            if owned is None:
                raise NativeProviderRejected("native_provider_fence_invalid")
            key, registered = owned
            if self._providers.get(key) is not registered:
                raise NativeProviderRejected("native_provider_registration_changed")

    def _selected(self, provider_ref, native_authority, selection):
        if type(selection) is not NativeSelection:
            raise TypeError("an actual typed Core NativeSelection is required")
        selection = NativeSelection.model_validate_json(selection.model_dump_json())
        with self._lock:
            registered = self._providers.get((provider_ref, native_authority))
        if registered is None:
            return selection, None, "native_provider_not_registered"
        if registered.admission.selection != selection:
            return selection, None, "native_provider_selection_changed"
        return selection, registered, None

    @staticmethod
    def _unverified(provider_ref, native_authority, selection, reason, *, state="unknown"):
        return ExistingSessionProof(state=state, reason_code=reason, provider_ref=provider_ref,
            native_authority=native_authority, selection=selection, host_ref=selection.host_ref)

    def prove(self, provider_ref: str, native_authority: str, selection: NativeSelection) -> ExistingSessionProof:
        selection, registered, reason = self._selected(provider_ref, native_authority, selection)
        if reason:
            return self._unverified(provider_ref, native_authority, selection, reason)
        if registered.proof_port is None:
            return self._unverified(provider_ref, native_authority, selection, "native_host_extension_missing",
                                    state="unsupported")
        _clock(self.clock)
        try:
            snapshot = registered.proof_port.existing_session(selection)
        except NativeProviderRejected as error:
            reason = str(error)
            if reason not in {"native_endpoint_selection_changed", "native_endpoint_changed_during_readback"}:
                reason = "native_provider_readback_rejected"
            return self._unverified(provider_ref, native_authority, selection, reason)
        except (ConnectionError, TimeoutError):
            return self._unverified(provider_ref, native_authority, selection, "native_host_disconnected",
                                    state="disconnected")
        except DeliveryBoundaryRejected as error:
            reason = str(error)
            if reason not in {"receiver_projection_binding_changed", "receiver_projection_node_changed",
                              "native_session_changed", "native_binding_or_claim_changed", "native_kernel_claim_lost",
                              "native_binary_changed", "native_configuration_changed", "native_provider_generation_changed"}:
                reason = "native_receiver_binding_changed"
            return self._unverified(provider_ref, native_authority, selection, reason)
        except Exception:  # noqa: BLE001 - keep provider secrets out of observation errors.
            return self._unverified(provider_ref, native_authority, selection, "native_provider_readback_failed")
        now = _clock(self.clock)
        with self._lock:
            if self._providers.get((provider_ref, native_authority)) is not registered:
                return self._unverified(provider_ref, native_authority, selection, "native_provider_registration_changed")
        try:
            if type(snapshot) is not ReceiverSnapshot:
                raise ValueError("typed actual snapshot required")
            snapshot = ReceiverSnapshot.model_validate_json(snapshot.model_dump_json())
            return self._proof(registered.admission, snapshot, now)
        except (TypeError, ValueError):
            return self._unverified(provider_ref, native_authority, selection, "native_provider_evidence_invalid")

    def _proof(self, admission, snapshot, now):
        selection = admission.selection
        binding, scope = selection.binding, snapshot.capability_scope
        reject = lambda reason, **kwargs: self._unverified(admission.provider_ref,
            admission.native_authority, selection, reason, **kwargs)
        if ((snapshot.receiver_id, snapshot.address, snapshot.binding_epoch, scope.execution_host_ref) !=
                (binding.receiver_id, binding.actor_address, binding.binding_epoch, selection.host_ref)):
            return reject("native_source_selection_changed")
        if not scope.complete:
            reasons = [o.reason_code for o in snapshot.observations
                       if o.knowledge == "unknown" and o.reason_code]
            return reject(reasons[0] if reasons else "native_capability_scope_incomplete")
        if ((binding.provider_generation is not None and binding.provider_generation != scope.provider_generation)
                or (binding.native_session_ref is not None and binding.native_session_ref != snapshot.native_session_ref)):
            return reject("native_source_generation_changed")
        current = snapshot.current(now, scope=scope)
        axes = {observation.axis: observation for observation in current.observations}
        required = []
        for axis, expected in (("connection", "connected"), ("session", "present")):
            observation = axes.get(axis)
            if observation is not None and observation.knowledge == "unsupported":
                return reject(observation.reason_code or "native_existing_session_unsupported", state="unsupported")
            if observation is not None and observation.knowledge == "observed" and axis == "connection" and observation.value == "disconnected":
                return reject(observation.reason_code or "native_host_disconnected", state="disconnected")
            if (observation is None or observation.knowledge != "observed" or observation.source != "native_api"
                    or observation.value != expected or observation.evidence_ref is None):
                return reject(observation.reason_code if observation is not None and observation.reason_code
                              else "native_existing_session_unconfirmed")
            required.append(observation)
        if current.native_session_ref is None:
            return reject("native_existing_session_unconfirmed")
        observed_at = max(observation.observed_at for observation in required)
        expires_at = min(*(observation.expires_at for observation in required),
                         *(observation.observed_at + self.proof_ttl for observation in required))
        if not observed_at <= now < expires_at:
            return reject("native_proof_expired")
        references = tuple(dict.fromkeys(observation.evidence_ref for observation in required))
        source = NativeSourceIdentity(provider_ref=admission.provider_ref, native_authority=admission.native_authority,
            selection=selection, host_ref=selection.host_ref, native_session_ref=current.native_session_ref,
            provider_generation=scope.provider_generation)
        return ExistingSessionProof(state="verified", reason_code=None, provider_ref=admission.provider_ref,
            native_authority=admission.native_authority, selection=selection, host_ref=selection.host_ref,
            native_session_ref=current.native_session_ref, provider_generation=scope.provider_generation,
            observed_at=observed_at, expires_at=expires_at, evidence_ref=references[-1], evidence_refs=references,
            intrinsic_capabilities=current.capabilities, snapshot=current.model_copy(update={"allowed_actions": ()}),
            source=source)

    def authorize_host(self, provider_ref: str, native_authority: str, selection: NativeSelection,
                       caller: NativeHostCaller, operation: str) -> HostAuthorizationResult:
        """Request separate Host permission; a link/proof never supplies it."""
        if operation not in HOST_OPERATIONS:
            return HostAuthorizationResult(state="unsupported", reason_code="native_host_operation_unsupported")
        if type(caller) is not NativeHostCaller:
            raise TypeError("a trusted facade-derived NativeHostCaller is required")
        caller = NativeHostCaller.model_validate_json(caller.model_dump_json())
        selection, registered, reason = self._selected(provider_ref, native_authority, selection)
        if reason:
            return HostAuthorizationResult(state="unknown", reason_code=reason)
        if (caller.tenant_id, caller.project_id) != (selection.tenant_id, selection.project_id):
            return HostAuthorizationResult(state="denied", reason_code="native_host_caller_project_changed")
        if registered.authorization_port is None:
            return HostAuthorizationResult(state="unsupported", reason_code="native_host_authorization_extension_missing")
        proof = self.prove(provider_ref, native_authority, selection)
        if proof.state != "verified":
            return HostAuthorizationResult(state="unknown", reason_code=proof.reason_code)
        try:
            result = registered.authorization_port.authorize(caller, proof.source, operation)
            if type(result) is not HostAuthorizationResult:
                raise ValueError("typed Host authorization required")
            result = HostAuthorizationResult.model_validate_json(result.model_dump_json())
            now = _clock(self.clock)
            with self._lock:
                if self._providers.get((provider_ref, native_authority)) is not registered:
                    return HostAuthorizationResult(state="unknown", reason_code="native_provider_registration_changed")
            if proof.current(now).state != "verified":
                return HostAuthorizationResult(state="unknown", reason_code="native_proof_expired")
            if result.state == "authorized":
                permission = result.permission
                if (permission.source != proof.source or permission.caller != caller or permission.operation != operation
                        or not permission.issued_at <= now < permission.expires_at):
                    return HostAuthorizationResult(state="denied", reason_code="native_host_permission_binding_changed")
            return result
        except Exception:  # noqa: BLE001 - untrusted extension failures cannot grant Host rights.
            return HostAuthorizationResult(state="unknown", reason_code="native_host_authorization_failed")
