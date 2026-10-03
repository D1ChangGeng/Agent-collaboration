"""OAuth resource server for the same project Domain used by stdio clients.

The Authorization Server owns consent and token issuance. Operator-configured
subject/client bindings select existing Domain Grants; OAuth claims never create
a principal, project membership, or permission. TLS is terminated by an explicitly
admitted ingress; the executable binds only to loopback.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from copy import copy
from dataclasses import replace
from urllib.parse import urlsplit

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field, field_validator, model_validator
from starlette.middleware.cors import CORSMiddleware

from runtime.mcp_runtime import McpRuntime
from runtime.project_mcp_server import create_project_server
from runtime.project_service import ProjectService
from runtime.surface_config import ConfigModel, PrivateReference
from runtime.surfaces import SharedService


def secure_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or "*" in value or any(c.isspace() for c in value)):
        raise ValueError("an exact HTTPS URL is required")
    return value


class OAuthBinding(ConfigModel):
    subject: str = Field(min_length=1, max_length=256)
    client_id: str = Field(min_length=1, max_length=256)
    principal_ref: str = Field(min_length=1, max_length=256)
    grant_ref: str = Field(min_length=1, max_length=256)
    profile: str = Field(min_length=1, max_length=128)


class ProjectHttpSettings(ConfigModel):
    schema_version: str = Field(default="acs-project-http/1", pattern=r"^acs-project-http/1$")
    issuer_url: str
    resource_url: str
    introspection_url: str
    introspection_client_id: str = Field(min_length=1, max_length=256)
    introspection_secret_ref: PrivateReference
    bindings: tuple[OAuthBinding, ...] = Field(min_length=1, max_length=256)
    allowed_origins: tuple[str, ...] = Field(default=(), max_length=16)
    authorization_refresh_seconds: int = Field(default=5, ge=1, le=5)
    presentation_timezone: str = "UTC"

    @field_validator("presentation_timezone")
    @classmethod
    def presentation_zone(cls, value):
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as error:
            raise ValueError("presentation timezone must be an available IANA timezone") from error
        return value


    @field_validator("issuer_url", "resource_url", "introspection_url")
    @classmethod
    def https_url(cls, value):
        return secure_url(value)

    @field_validator("allowed_origins")
    @classmethod
    def exact_origins(cls, values):
        for value in values:
            secure_url(value)
            if urlsplit(value).path:
                raise ValueError("Origin must not contain a path")
        return values

    @model_validator(mode="after")
    def validate_bindings(self):
        if urlsplit(self.resource_url).path != "/mcp":
            raise ValueError("this ingress profile serves the /mcp resource")
        identities = [(b.subject, b.client_id) for b in self.bindings]
        if len(set(identities)) != len(identities):
            raise ValueError("OAuth identities require unambiguous Domain bindings")
        return self


class IntrospectionVerifier:
    """Fail-closed RFC 7662 verifier; no redirect, discovery, or token passthrough."""

    def __init__(self, settings, client):
        self.settings, self.client = settings, client
        self.bindings = {(b.subject, b.client_id): b for b in settings.bindings}

    async def verify_token(self, token):
        if not isinstance(token, str) or not 1 <= len(token) <= 8192:
            return None
        try:
            async with self.client.stream("POST", self.settings.introspection_url,
                    data={"token": token, "token_type_hint": "access_token"},
                    auth=httpx.BasicAuth(self.settings.introspection_client_id,
                                        self.settings.introspection_secret_ref.resolve()),
                    timeout=5, follow_redirects=False) as response:
                if response.status_code != 200:
                    return None
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 65536:
                        return None
            claims = json.loads(body)
            if not isinstance(claims, dict) or claims.get("active") is not True:
                return None
            audience = claims.get("aud")
            audiences = [audience] if isinstance(audience, str) else audience
            if (not isinstance(audiences, list) or not all(isinstance(a, str) for a in audiences)
                    or self.settings.resource_url not in audiences
                    or claims.get("iss") != self.settings.issuer_url
                    or claims.get("token_type", "Bearer").lower() != "bearer"):
                return None
            if type(claims.get("exp")) is not int or claims["exp"] <= time.time():
                return None
            for field in ("nbf", "iat"):
                if field in claims and (type(claims[field]) is not int or claims[field] > time.time()):
                    return None
            subject, client_id = claims.get("sub"), claims.get("client_id")
            if (not isinstance(subject, str) or not isinstance(client_id, str)
                    or (subject, client_id) not in self.bindings):
                return None
            scope = claims.get("scope")
            if not isinstance(scope, str) or len(scope) > 16384:
                return None
            scopes = scope.split()
            if "acs:connect" not in scopes:
                return None
            return AccessToken(token=token, client_id=client_id, subject=subject,
                scopes=scopes, expires_at=claims["exp"], resource=self.settings.resource_url,
                claims={"iss": self.settings.issuer_url, "acs/checked_at": time.monotonic()})
        except Exception:  # noqa: BLE001 - network/issuer/configuration errors deny access without leaking values
            return None


class TokenAuthorization:
    """A bounded introspection observation, rechecked by every protected action."""

    def __init__(self, access, context, verifier):
        self.access, self.context, self.verifier = access, context, verifier
        self.checked_at = access.claims["acs/checked_at"]
        self.valid = True

    def credential(self):
        if (not self.valid or self.access.expires_at <= time.time()
                or time.monotonic() - self.checked_at > self.verifier.settings.authorization_refresh_seconds):
            raise PermissionError("OAuth authorization observation expired")
        return self.access.token

    def authenticate(self, credential):
        if not isinstance(credential, str) or not hmac.compare_digest(credential, self.credential()):
            raise PermissionError("OAuth credential rejected")
        return self.context

    async def refresh(self):
        if time.monotonic() - self.checked_at >= self.verifier.settings.authorization_refresh_seconds / 2:
            access = await self.verifier.verify_token(self.access.token)
            self.valid = access is not None and (access.subject, access.client_id) == (
                self.access.subject, self.access.client_id)
            if self.valid:
                self.access, self.checked_at = access, time.monotonic()
        self.credential()

    def authorize_tool(self, catalog, name):
        self.credential()
        required = catalog["tools"][name]["security_scopes"]
        if not set(required) <= set(self.access.scopes):
            raise PermissionError("OAuth tool scope is unavailable")


class OAuthProjectService(ProjectService):
    """OAuth scopes narrow (and never replace) live Domain authorization."""

    def __init__(self, *args, token_authorization, **kwargs):
        super().__init__(*args, **kwargs)
        self.token_authorization = token_authorization

    def _authorize(self, authority, cursor, project_id, name, args):
        self.token_authorization.authorize_tool(self.catalog, name)
        return super()._authorize(authority, cursor, project_id, name, args)

    def available_tools(self, credential):
        allowed = set(self.token_authorization.access.scopes)
        candidates = [name for name in self.catalog["profiles"][self.profile]
                      if set(self.catalog["tools"][name]["security_scopes"]) <= allowed]
        return self._discover_tools(credential, candidates)

    def execute(self, name, args, credential):
        self.token_authorization.authorize_tool(self.catalog, name)
        return super().execute(name, args, credential)

    def _profile_snapshot(self):
        state, data, followups = super()._profile_snapshot()
        access = self.token_authorization.access
        return state, dict(data, transport_authorization={
            "kind": "oauth_introspection", "issuer": access.claims["iss"],
            "security_scopes": sorted(access.scopes), "expires_at": access.expires_at,
            "refresh_bound_seconds": self.token_authorization.verifier.settings.authorization_refresh_seconds,
        }), followups


def create_http_app(service, catalog, settings, *, sources=None, host="127.0.0.1", port=8765, client=None):
    """Construct a multi-principal endpoint; no provisioning or listener side effects."""
    if any(b.profile not in catalog["profiles"] for b in settings.bindings):
        raise ValueError("OAuth binding refers to an unknown Profile")
    owns_client = client is None
    client = client or httpx.AsyncClient(trust_env=False)
    verifier = IntrospectionVerifier(settings, client)

    def runtime_for_request():
        access = get_access_token()
        if access is None:
            raise PermissionError("OAuth authentication required")
        binding = verifier.bindings.get((access.subject, access.client_id))
        if binding is None:
            raise PermissionError("OAuth identity is not admitted")
        authority = copy(service.authority)
        authority.context = replace(authority.context, principal_ref=binding.principal_ref,
            grant_ref=binding.grant_ref, credential_hash=hashlib.sha256(access.token.encode()).hexdigest())
        authorization = TokenAuthorization(access, authority.context, verifier)
        shared = SharedService(authority, authorization)
        projects = OAuthProjectService(shared, catalog, profile=binding.profile, sources=sources,
                                       token_authorization=authorization)
        runtime = McpRuntime(projects, authorization.credential,
                             presentation_timezone=settings.presentation_timezone)
        runtime.refresh_authorization = authorization.refresh
        return runtime

    server = create_project_server(runtime_provider=runtime_for_request)
    local_host = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    app = server.streamable_http_app(host=host, token_verifier=verifier,
        auth=AuthSettings(issuer_url=settings.issuer_url, resource_server_url=settings.resource_url,
                          required_scopes=["acs:connect"], validate_token_resource=True),
        transport_security=TransportSecuritySettings(allowed_hosts=[urlsplit(settings.resource_url).netloc, local_host],
            allowed_origins=list(settings.allowed_origins)),
        max_request_body_size=131072, max_sessions=64, session_idle_timeout=300)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        try:
            async with original_lifespan(application) as state:
                yield state
        finally:
            if owns_client:
                await client.aclose()

    app.router.lifespan_context = lifespan
    if settings.allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.allowed_origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Mcp-Session-Id", "MCP-Protocol-Version", "Last-Event-ID"],
            expose_headers=["Mcp-Session-Id", "WWW-Authenticate"], max_age=300)
    return app
