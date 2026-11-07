from __future__ import annotations

import ipaddress
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from runtime.artifacts import LocalArtifactStore
from runtime.auth import LocalCredentialAuthenticator
from runtime.delivery_node import LocalNodeEndpoint
from runtime.domain import DomainAuthority
from runtime.models import AuthenticatedContext
from runtime.operator_files import OperatorFileError, read_operator_file
from runtime.recovery_models import BoundaryRejected
from runtime.scoped_artifacts import ScopedArtifactStores
from runtime.surfaces import SharedService


class ConfigurationError(RuntimeError):
    pass


class ConfigModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PrivateReference(ConfigModel):
    kind: Literal["environment", "file"]
    name: str = Field(min_length=1, max_length=4096)

    def resolve(self):
        if self.kind == "environment":
            value = os.environ.get(self.name)
            if not value or len(value.encode("utf-8")) > 65536:
                raise ConfigurationError("private reference is unavailable")
            return value
        path = Path(self.name)
        if not path.is_absolute() or os.name == "nt":
            # Windows uses an operator-injected process-environment reference.
            # POSIX permission bits must not masquerade as a Windows ACL check.
            raise ConfigurationError("private file reference backend is unavailable")
        try:
            value = read_operator_file(path).decode("utf-8").rstrip("\r\n")
            if not value or len(value.encode()) > 65536:
                raise ConfigurationError("private reference is invalid")
            return value
        except (OperatorFileError, OSError, UnicodeError):
            raise ConfigurationError("private reference is unavailable") from None


class RoleContext(ConfigModel):
    tenant_id: str = Field(min_length=1, max_length=256)
    authority_id: str = Field(min_length=1, max_length=256)
    authority_incarnation: str = Field(min_length=1, max_length=256)
    principal_ref: str = Field(min_length=1, max_length=256)
    grant_ref: str = Field(min_length=1, max_length=256)
    credential_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    agent_slot_id: str | None = Field(default=None, min_length=1, max_length=256)
    trusted_client: bool = False


class ArtifactSettings(ConfigModel):
    root: str
    scope_id: str
    authorized_source_roots: tuple[str, ...] = ()
    max_bytes: int = Field(default=16 * 1024 * 1024, ge=1, le=256 * 1024 * 1024)

    @field_validator("root")
    @classmethod
    def absolute_root(cls, value):
        if not Path(value).is_absolute():
            raise ValueError("artifact root must be absolute")
        return value


class CommunicationAttachmentSettings(ConfigModel):
    file_bytes: int = Field(default=20 * 1024 * 1024, ge=1, le=256 * 1024 * 1024)
    message_count: int = Field(default=8, ge=1, le=8)
    message_bytes: int = Field(default=50 * 1024 * 1024, ge=1, le=1024**3)
    viewer_staging_bytes: int = Field(default=100 * 1024 * 1024, ge=1, le=8 * 1024**3)
    project_staging_bytes: int = Field(default=1024 * 1024 * 1024, ge=1, le=64 * 1024**3)
    staging_seconds: int = Field(default=24 * 3600, ge=60, le=7 * 86400)

    @model_validator(mode="after")
    def admit_one_file(self):
        if min(self.message_bytes, self.viewer_staging_bytes, self.project_staging_bytes) < self.file_bytes:
            raise ValueError("attachment budgets must admit the configured per-file limit")
        return self

    def to_limits(self):
        from runtime.communication_attachment_storage import AttachmentLimits

        return AttachmentLimits(file_bytes=self.file_bytes, attachments_per_message=self.message_count,
            message_bytes=self.message_bytes, viewer_bytes=self.viewer_staging_bytes,
            project_bytes=self.project_staging_bytes, reservation_ttl_seconds=self.staging_seconds,
            chunk_bytes=65536, upload_lease_seconds=min(900, self.staging_seconds))


class CommunicationNativeLinkSettings(ConfigModel):
    links_per_scope: int = Field(default=1024, ge=1, le=1000000)
    history_per_link: int = Field(default=4096, ge=1, le=1000000)
    requests_per_viewer: int = Field(default=16384, ge=1, le=10000000)
    metadata_bytes: int = Field(default=65536, ge=1, le=262144)

    def to_limits(self):
        from runtime.communication_native_link_storage import NativeLinkLimits

        return NativeLinkLimits(**self.model_dump())


class EffectSettings(ConfigModel):
    root: str
    scope_id: str
    resource_paths: dict[str, str]

    @field_validator("root")
    @classmethod
    def absolute_root(cls, value):
        if not Path(value).is_absolute():
            raise ValueError("effect root must be absolute")
        return value


class RemoteEndpointSettings(ConfigModel):
    endpoint_id: str = Field(min_length=1, max_length=256)
    authority_signing_key_ref: PrivateReference
    journal_generation: int = Field(default=1, ge=1)
    request_timeout_seconds: int = Field(default=30, ge=1, le=120, strict=True)
    old_boot_isolation_ref: str | None = None
    prepare_argv: tuple[str, ...] = Field(default=(), max_length=64)
    lifecycle_control: bool = Field(default=False, strict=True)
    message_wake: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def wake_requires_control(self):
        if self.message_wake and not self.lifecycle_control:
            raise ValueError("message wake requires the fenced lifecycle transport")
        return self

    @field_validator("prepare_argv")
    @classmethod
    def valid_preparation(cls, values):
        if any(not value or len(value) > 4096 or "\0" in value for value in values):
            raise ValueError("machine preparation arguments are invalid")
        return values


class FilesystemSshMachine(ConfigModel):
    machine_id: str
    ssh_target: str
    service_argv: tuple[str, ...]
    allowed_operations: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def safe_service_arguments(self):
        import re
        if not re.fullmatch(r"[A-Za-z0-9_@.-]+", self.ssh_target) or self.ssh_target.startswith("-"):
            raise ValueError("SSH target is invalid")
        if not self.service_argv or any(not value or "\0" in value for value in self.service_argv):
            raise ValueError("SSH file service command is invalid")
        from runtime.machine_filesystem import TOOLS
        if self.allowed_operations is not None and (len(set(self.allowed_operations)) != len(self.allowed_operations)
                or set(self.allowed_operations) - (TOOLS | {"filesystem_context"})):
            raise ValueError("SSH file operations are invalid")
        return self


class FilesystemSettings(ConfigModel):
    default_machine_id: str = "local"
    cwd: str | None = None
    management_machine_id: str | None = None
    ssh_machines: tuple[FilesystemSshMachine, ...] = ()


class SurfaceSettings(ConfigModel):
    schema_version: Literal["acs-surfaces/1"] = "acs-surfaces/1"
    access_mode: Literal["owner", "shared"] = "shared"
    context: RoleContext
    dsn_ref: PrivateReference
    credential_ref: PrivateReference
    artifacts: ArtifactSettings | None = None
    additional_artifacts: tuple[ArtifactSettings, ...] = Field(default=(), max_length=63)
    # Accepted for existing operator files; task Effect/Lease services are no
    # longer constructed. Artifacts and source access keep their own policy.
    effects: EffectSettings | None = None
    remote_endpoints: tuple[RemoteEndpointSettings, ...] = Field(default=(), max_length=64)
    filesystem: FilesystemSettings = Field(default_factory=FilesystemSettings)
    temporal_endpoint: str | None = None
    delivery_maintenance: Literal["auto", "external"] = "auto"
    receiver_evidence: bool = False
    wait_ingress_recovery: bool = False
    notification_frontiers: bool = False
    communication_client_api: bool = False
    communication_event_stream: bool = False
    communication_attachments: CommunicationAttachmentSettings | None = None
    communication_native_links: CommunicationNativeLinkSettings | None = None
    presentation_timezone: str = "UTC"

    @field_validator("presentation_timezone")
    @classmethod
    def supported_presentation_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as error:
            raise ValueError("presentation timezone must be an available IANA timezone") from error
        return value

    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)

    @model_validator(mode="after")
    def unique_artifact_scopes(self):
        scopes = [item.scope_id for item in self.artifact_configs()]
        if len(scopes) != len(set(scopes)):
            raise ValueError("duplicate artifact Scope configuration")
        if self.communication_attachments is not None:
            if not self.communication_client_api:
                raise ValueError("attachment service requires the communication client facade")
            stores = self.artifact_configs()
            if not stores or any(store.max_bytes < self.communication_attachments.file_bytes for store in stores):
                raise ValueError("attachment service requires explicit Scope CAS capacity for its file limit")
        if self.communication_native_links is not None and not self.communication_client_api:
            raise ValueError("Native links require the communication client facade")
        return self

    def artifact_configs(self):
        return ([self.artifacts] if self.artifacts else []) + list(self.additional_artifacts)

    @field_validator("host")
    @classmethod
    def loopback_only(cls, value):
        if not ipaddress.ip_address(value).is_loopback:
            raise ValueError("this profile only supports loopback listeners")
        return value

    def credential(self):
        try:
            return self.credential_ref.resolve()
        except ConfigurationError:
            return None


def load_settings(path):
    try:
        data = read_operator_file(path)
        return SurfaceSettings.model_validate_json(data, strict=True)
    except (OSError, ValueError, TypeError, ConfigurationError, OperatorFileError):
        raise ConfigurationError("trusted configuration is unavailable or invalid") from None


def trusted_local_node_response_reader(endpoints):
    """Bind a projection readback to operator-supplied local Node endpoints."""
    if not endpoints:
        return None

    def read(identity):
        endpoint = endpoints.get(identity.endpoint_id)
        if not isinstance(endpoint, LocalNodeEndpoint):
            raise BoundaryRejected("trusted local Node endpoint is unavailable")
        descriptor = endpoint.descriptor()
        if (descriptor["machine_id"], descriptor["node_id"], descriptor["boot_incarnation"]) != (
            identity.machine_id, identity.node_id, identity.boot_incarnation
        ):
            raise BoundaryRejected("trusted local Node identity changed")
        return endpoint.journal.response_outbox().by_invocation(identity)

    return read


@contextmanager
def configured_service(path, *, delivery_endpoints=None, expected_settings=None):
    settings = load_settings(path)
    if expected_settings is not None and settings != expected_settings:
        raise ConfigurationError("trusted configuration changed after preflight")
    with ExitStack() as resources:
        store = None
        stores = [resources.enter_context(LocalArtifactStore(config.root, scope_id=config.scope_id,
                  authorized_source_roots=config.authorized_source_roots, max_bytes=config.max_bytes))
                  for config in settings.artifact_configs()]
        if stores:
            store = stores[0] if len(stores) == 1 else ScopedArtifactStores(stores)
        context = AuthenticatedContext(**settings.context.model_dump())
        domain = DomainAuthority(settings.dsn_ref.resolve(), context=context, artifact_store=store,
                                 authority_binding=(context.authority_id, context.authority_incarnation),
                                 access_mode=settings.access_mode,
                                 delivery_endpoints=delivery_endpoints,
                                 node_response_reader=trusted_local_node_response_reader(delivery_endpoints))
        domain._filesystem_settings = settings.filesystem
        domain._communication_maintenance_mode = settings.delivery_maintenance
        domain._receiver_evidence_enabled = settings.receiver_evidence
        domain._wait_ingress_recovery_enabled = settings.wait_ingress_recovery
        domain._notification_frontiers_enabled = settings.notification_frontiers
        domain._communication_client_api_enabled = settings.communication_client_api
        domain._communication_events_enabled = settings.communication_event_stream
        domain._communication_attachment_settings = settings.communication_attachments
        domain._communication_attachments_enabled = settings.communication_attachments is not None
        domain._communication_native_link_settings = settings.communication_native_links
        domain._communication_native_links_enabled = settings.communication_native_links is not None
        if settings.remote_endpoints:
            from runtime.machine_connections import ConfiguredRemoteEndpoint

            def current_endpoint(endpoint_id):
                current = load_settings(path)
                if (current.context != settings.context or current.access_mode != settings.access_mode
                        or current.dsn_ref != settings.dsn_ref or current.credential_ref != settings.credential_ref
                        or current.dsn_ref.resolve() != domain._dsn):
                    raise ConfigurationError("trusted identity changed; reconnect this client")
                matches = [item for item in current.remote_endpoints if item.endpoint_id == endpoint_id]
                if len(matches) != 1:
                    raise ConfigurationError("configured endpoint changed; reconnect this client")
                return matches[0]

            def message_wake_enabled(endpoint_id):
                if endpoint_id not in {item.endpoint_id for item in settings.remote_endpoints}:
                    return False
                selected = current_endpoint(endpoint_id)
                return selected.lifecycle_control and selected.message_wake

            domain._receiver_message_wake_policy = message_wake_enabled

            for target in settings.remote_endpoints:
                if target.endpoint_id in domain._delivery_endpoints:
                    raise ConfigurationError("duplicate configured execution endpoint")
                domain._delivery_endpoints[target.endpoint_id] = ConfiguredRemoteEndpoint(
                    domain, target, settings_provider=current_endpoint)
                if target.lifecycle_control:
                    from runtime.receiver_lifecycle_transport import ConfiguredLifecycleTransport

                    if not hasattr(domain, "_receiver_lifecycle_transports"):
                        domain._receiver_lifecycle_transports = {}
                    domain._receiver_lifecycle_transports[target.endpoint_id] = ConfiguredLifecycleTransport(
                        domain._delivery_endpoints[target.endpoint_id])
        yield SharedService(domain, LocalCredentialAuthenticator(context)), settings
