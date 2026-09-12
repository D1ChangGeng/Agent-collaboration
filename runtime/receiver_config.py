from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from runtime.receiver_crypto import key_fingerprint, verify
from runtime.receiver_models import EndpointBinding, EndpointRegistration
from runtime.receiver_paths import (
    PathSecurityRejected,
    optional_private_file_identity,
    require_posix,
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
    def __init__(self, allowed: dict[str, ConnectionTarget], current_node: NodeIdentity):
        self.allowed = dict(allowed)
        self.current_node = current_node
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
        if registration.expires_at <= datetime.now(UTC):
            raise BootstrapRejected("endpoint registration is expired")
        address = ipaddress.ip_address(target.host)
        if target.route_class == "loopback" and not address.is_loopback:
            raise BootstrapRejected("loopback connection reference is not loopback")
        if target.route_class in ("private", "tunnel") and not address.is_private:
            raise BootstrapRejected("private connection reference is not private")
        verify(node.node_public_key, signature, registration)
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
class ReceiverRuntimeConfig:
    binding: EndpointBinding
    authority_key_id: str
    authority_key_revision: int
    authority_public_key: str
    authority_public_key_fingerprint: str
    tls_cert_path: str
    tls_key_path: str
    node_signing_key_path: str
    ledger_path: str
    expected_boot_incarnation: str
    journal_generation: int
    old_boot_isolation_ref: str | None = None
    maximum_body_bytes: int = 65_536
    clock_skew_seconds: int = 5

    def validate(self) -> None:
        try:
            require_posix()
        except PathSecurityRejected:
            raise BootstrapRejected("receiver runtime is POSIX-only until Windows ACL admission exists") from None
        if key_fingerprint(self.authority_public_key) != self.authority_public_key_fingerprint:
            raise BootstrapRejected("authority transport-key fingerprint differs")
        verify(self.binding.node_public_key, self.binding.registration_signature,
               self.binding.registration)
        if self.binding.registration.expires_at <= datetime.now(UTC):
            raise BootstrapRejected("endpoint registration is expired")
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
        if not 1_024 <= self.maximum_body_bytes <= 1_048_576 or not 0 <= self.clock_skew_seconds <= 30:
            raise BootstrapRejected("receiver bounds are invalid")
        if (self.expected_boot_incarnation != self.binding.registration.boot_incarnation
                or self.journal_generation < 1
                or (self.journal_generation == 1) != (self.old_boot_isolation_ref is None)):
            raise BootstrapRejected("receiver boot/generation/isolation configuration is invalid")
