from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from runtime import receiver_paths
from runtime.connection_clock import ClockUnavailable, ConnectionClock
from runtime.receiver_crypto import key_fingerprint, verify
from runtime.receiver_models import EndpointBinding, EndpointRegistration
from runtime.receiver_paths import (
    PathSecurityRejected,
    optional_private_file_identity,
    validated_file_identity,
)


class BootstrapRejected(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ConnectionTarget:
    connection_ref: str
    host: str
    port: int
    route_class: str


@dataclass(frozen=True, slots=True)
class NodeIdentity:
    tenant_id: str
    authority_id: str
    authority_incarnation: str
    node_id: str
    node_binding_revision: int
    runtime_id: str
    runtime_revision: int
    machine_id: str
    boot_incarnation: str
    scope_id: str
    agent_slot_id: str
    node_key_id: str
    node_public_key: str


class EndpointBootstrap:
    def __init__(self, allowed: dict[str, ConnectionTarget], current_node: NodeIdentity,
                 *, clock: ConnectionClock | None = None):
        self.allowed = dict(allowed)
        self.current_node = current_node
        self.clock = clock
        self._registrations: dict[str, tuple[str, EndpointBinding]] = {}

    def register(self, registration: EndpointRegistration, signature: str) -> EndpointBinding:
        target = self.allowed.get(registration.connection_ref)
        node = self.current_node
        expected = (
            node.tenant_id, node.authority_id, node.authority_incarnation, node.node_id,
            node.node_binding_revision, node.runtime_id, node.runtime_revision, node.machine_id,
            node.boot_incarnation, node.scope_id, node.agent_slot_id,
        )
        actual = (
            registration.tenant_id, registration.authority_id, registration.authority_incarnation,
            registration.node_id, registration.node_binding_revision, registration.runtime_id,
            registration.runtime_revision, registration.machine_id, registration.boot_incarnation,
            registration.scope_id, registration.agent_slot_id,
        )
        if target is None or actual != expected:
            raise BootstrapRejected("endpoint registration target is not current or allowlisted")
        address = ipaddress.ip_address(target.host)
        if target.route_class == "loopback" and not address.is_loopback:
            raise BootstrapRejected("loopback connection reference is not loopback")
        if target.route_class in ("private", "tunnel") and not address.is_private:
            raise BootstrapRejected("private connection reference is not private")
        verify(node.node_public_key, signature, registration)
        clock = self.clock
        if clock is None and target.route_class == "loopback":
            clock = ConnectionClock.local(reference=lambda: datetime.now(UTC))
        if clock is not None:
            try:
                clock.require_before(registration.expires_at)
            except ClockUnavailable as error:
                raise BootstrapRejected("endpoint registration time is unavailable or expired") from error
        binding = EndpointBinding(
            registration=registration, locator_host=target.host, locator_port=target.port,
            route_class=target.route_class, node_key_id=node.node_key_id,
            node_public_key=node.node_public_key, registration_signature=signature,
        )
        from runtime.receiver_crypto import sha256
        identity = sha256(registration)
        previous = self._registrations.get(registration.registration_id)
        if previous and previous[0] != identity:
            raise BootstrapRejected("endpoint registration replay changed")
        self._registrations[registration.registration_id] = (identity, binding)
        return binding


@dataclass(frozen=True, slots=True)
class ReceiverClientConfig:
    binding: EndpointBinding
    authority_key_id: str
    authority_key_revision: int
    authority_public_key: str
    authority_public_key_fingerprint: str
    expected_boot_incarnation: str
    journal_generation: int
    old_boot_isolation_ref: str | None = None
    maximum_body_bytes: int = 65_536
    clock_skew_seconds: int = 5

    def validate(self) -> None:
        if key_fingerprint(self.authority_public_key) != self.authority_public_key_fingerprint:
            raise BootstrapRejected("authority transport-key fingerprint differs")
        verify(self.binding.node_public_key, self.binding.registration_signature,
               self.binding.registration)
        # Expiry belongs to the Runtime clock after cryptographic binding validation.
        if not 1_024 <= self.maximum_body_bytes <= 1_048_576 or not 0 <= self.clock_skew_seconds <= 30:
            raise BootstrapRejected("receiver bounds are invalid")
        if (self.expected_boot_incarnation != self.binding.registration.boot_incarnation
                or self.journal_generation < 1
                or (self.journal_generation == 1) != (self.old_boot_isolation_ref is None)):
            raise BootstrapRejected("receiver boot/generation/isolation configuration is invalid")


@dataclass(frozen=True, slots=True)
class ReceiverRuntimeConfig(ReceiverClientConfig):
    tls_cert_path: str = ""
    tls_key_path: str = ""
    node_signing_key_path: str = ""
    ledger_path: str = ""
    listen_host: str | None = None
    listen_port: int | None = None
    drop_response_after_commit_once: str | None = None

    def validate(self) -> None:
        ReceiverClientConfig.validate(self)
        if os.name not in {"posix", "nt"}:
            raise BootstrapRejected("receiver runtime path backend is unavailable")
        if receiver_paths.PLATFORM != os.name:
            raise BootstrapRejected("receiver runtime path backend differs from the running OS")
        for path in (self.tls_cert_path, self.tls_key_path, self.node_signing_key_path,
                     self.ledger_path):
            if not Path(path).is_absolute():
                raise BootstrapRejected("receiver paths must be absolute")
        try:
            validated_file_identity(self.tls_cert_path, private=False)
            validated_file_identity(self.tls_key_path, private=True)
            validated_file_identity(self.node_signing_key_path, private=True)
            optional_private_file_identity(self.ledger_path)
        except PathSecurityRejected:
            raise BootstrapRejected(
                "receiver path identity, private parent or owner-only mode rejected"
            ) from None
        if (self.listen_host is None) != (self.listen_port is None):
            raise BootstrapRejected("receiver local listener override is incomplete")
        if self.listen_host is not None:
            try:
                address = ipaddress.ip_address(self.listen_host)
            except ValueError:
                raise BootstrapRejected("receiver local listener address is invalid") from None
            if not address.is_loopback or not 1 <= self.listen_port <= 65535:
                raise BootstrapRejected("receiver local listener override must be loopback")
        if self.drop_response_after_commit_once not in {
            None, "delivery.prepare", "delivery.dispatch", "delivery.readback", "delivery.recover",
        }:
            raise BootstrapRejected("receiver response fault purpose is invalid")


def receiver_clock_identity(config: ReceiverClientConfig) -> dict:
    registration = config.binding.registration
    return {name: getattr(registration, name) for name in (
        "tenant_id", "authority_id", "authority_incarnation", "connection_ref", "endpoint_id",
        "endpoint_revision", "runtime_id", "runtime_revision", "node_id",
        "node_binding_revision", "machine_id", "boot_incarnation", "scope_id", "agent_slot_id",
    )} | {"journal_generation": config.journal_generation}


def resolve_connection_clock(config: ReceiverClientConfig,
                             clock: ConnectionClock | None = None) -> ConnectionClock:
    """Acquire time only from the trusted Runtime provider for this binding."""
    identity = receiver_clock_identity(config)
    if clock is None:
        if config.binding.route_class != "loopback":
            raise BootstrapRejected("a bound Authority clock is required for the receiver connection")
        clock = ConnectionClock.local(reference=lambda: datetime.now(UTC), identity=identity)
    if not isinstance(clock, ConnectionClock):
        raise BootstrapRejected("receiver ConnectionClock provider is invalid")
    try:
        reading = clock.require_before(config.binding.registration.expires_at)
    except ClockUnavailable as error:
        raise BootstrapRejected("endpoint registration time is unavailable or expired") from error
    observed = reading.identity
    if any(name in observed and observed[name] != value for name, value in identity.items()):
        raise BootstrapRejected("receiver clock connection identity differs")
    if config.binding.route_class != "loopback" and (
        reading.reference_id != f"domain:{identity['authority_id']}:{identity['authority_incarnation']}"
        or any(observed.get(name) != value for name, value in identity.items())
    ):
        raise BootstrapRejected("receiver clock Authority identity is unavailable")
    return clock
