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
from runtime.effects import LocalFileEffectGateway
from runtime.models import AuthenticatedContext, EffectReadback
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


class SurfaceSettings(ConfigModel):
    schema_version: Literal["acs-surfaces/1"] = "acs-surfaces/1"
    context: RoleContext
    dsn_ref: PrivateReference
    credential_ref: PrivateReference
    artifacts: ArtifactSettings | None = None
    additional_artifacts: tuple[ArtifactSettings, ...] = Field(default=(), max_length=63)
    effects: EffectSettings | None = None
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
                                 delivery_endpoints=delivery_endpoints,
                                 node_response_reader=trusted_local_node_response_reader(delivery_endpoints))
        if settings.effects:
            config = settings.effects
            gateway = resources.enter_context(LocalFileEffectGateway(domain.leases, config.root,
                scope_id=config.scope_id, resource_paths=config.resource_paths))
            domain._effect_registration_gateway = gateway
            def actual_readback(cursor, caller, effect):
                observed = gateway.historical_readback_in_transaction(
                    cursor, lease_id=effect["lease_id"], resource_id=effect["resource_id"],
                    generation=effect["generation"], fencing_token=effect["fencing_token"],
                    readback_ref=effect["readback_ref"], caller=caller, scope_id=effect["scope_id"],
                    grant_ref=caller.grant_ref, authority_incarnation=caller.authority_incarnation,
                    expected_operation_id=effect["operation_id"],
                )
                return {**{key: observed[key] for key in EffectReadback.model_fields
                           if key not in ("effect_id", "work_item_id")},
                        "effect_id": effect["effect_id"], "work_item_id": effect["work_item_id"]}
            domain._effect_readback_verifier = actual_readback
        yield SharedService(domain, LocalCredentialAuthenticator(context)), settings
