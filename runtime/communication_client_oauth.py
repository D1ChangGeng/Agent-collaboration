"""The same operator-established OAuth bindings for the client REST facade."""
from __future__ import annotations

import hashlib
from copy import copy
from dataclasses import replace

import httpx

from runtime.communication_http import (
    CommunicationHttpError,
    CommunicationHttpLimits,
    create_communication_app,
)
from runtime.project_http import IntrospectionVerifier, OAuthProjectService, TokenAuthorization
from runtime.surfaces import SharedService


class OAuthCommunicationProvider:
    def __init__(self, shared, catalog, settings, *, sources=None, client=None):
        self.shared, self.catalog, self.settings, self.sources = shared, catalog, settings, sources
        self.client = client or httpx.AsyncClient(trust_env=False)
        self.owns_client = client is None
        self.verifier = IntrospectionVerifier(settings, self.client)

    async def __call__(self, request):
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise CommunicationHttpError("unauthenticated", "OAuth bearer is required", status_code=401)
        token = header[7:]
        access = await self.verifier.verify_token(token)
        if access is None:
            raise CommunicationHttpError("unauthenticated", "OAuth binding is not active", status_code=401)
        binding = self.verifier.bindings.get((access.subject, access.client_id))
        if binding is None or binding.profile not in self.catalog["profiles"]:
            raise CommunicationHttpError("unauthenticated", "OAuth binding is unavailable", status_code=401)
        authority = copy(self.shared.authority)
        authority.context = replace(authority.context, principal_ref=binding.principal_ref, grant_ref=binding.grant_ref,
            credential_hash=hashlib.sha256(token.encode()).hexdigest(), agent_slot_id=binding.agent_slot_id,
            trusted_client=binding.trusted_client)
        authorization = TokenAuthorization(access, authority.context, self.verifier)
        projects = OAuthProjectService(SharedService(authority, authorization), self.catalog,
            profile=binding.profile, sources=self.sources, token_authorization=authorization)
        return projects, authorization.credential()

    async def close(self):
        if self.owns_client:
            await self.client.aclose()


def create_oauth_communication_app(shared, catalog, settings, *, sources=None, client=None):
    enabled = settings.communication_attachments
    configuration = getattr(shared.authority, "_communication_attachment_settings", None)
    if enabled and configuration is None:
        raise ValueError("attachment HTTP requires explicit Runtime attachment configuration")
    shared.authority._communication_attachments_enabled = enabled
    native_enabled = settings.communication_native_links
    native_configuration = getattr(shared.authority, "_communication_native_link_settings", None)
    if native_enabled and (native_configuration is None or getattr(shared.authority, "_native_provider_registry", None) is None):
        raise ValueError("Native links require Runtime limits and an admitted provider registry")
    shared.authority._communication_native_links_enabled = native_enabled
    configured_limits = {"attachment_bytes": configuration.file_bytes,
        "attachment_count": configuration.message_count, "attachment_total_bytes": configuration.message_bytes,
        "attachment_staging_bytes": configuration.viewer_staging_bytes,
        "attachment_project_staging_bytes": configuration.project_staging_bytes,
        "attachment_staging_seconds": configuration.staging_seconds} if enabled else {}
    if native_enabled:
        configured_limits.update(native_link_count=native_configuration.links_per_scope,
            native_link_history_revisions=native_configuration.history_per_link,
            native_link_write_receipts=native_configuration.requests_per_viewer,
            native_link_metadata_bytes=native_configuration.metadata_bytes)
    limits = CommunicationHttpLimits(**configured_limits)
    provider = OAuthCommunicationProvider(shared, catalog, settings, sources=sources, client=client)
    event_features = ["snapshot", "events"] if settings.communication_event_stream else []
    attachment_features = ["attachment_uploads", "attachments"] if enabled else []
    native_features = ["native_links", "native_source"] if native_enabled else []
    app = create_communication_app(provider, limits=limits, public_meta={"schema_version": "acs-client/1", "server_version": "2.3.1",
        "authority_id": shared.authority.context.authority_id, "authority_incarnation": shared.authority.context.authority_incarnation,
        "features": ["profile", "projects", "routes", "contacts", "messages", "send", "wait", "delivery", "operations",
                     "conversations", "conversation_resolve", "conversation_detail", "read_state", "preferences", "drafts", "search", "receivers", "receiver_recovery", "notices", *event_features, *attachment_features, *native_features],
        "limits": {field: getattr(limits, field) for field in ("message_bytes", "page_items", "attachment_count", "attachment_total_bytes",
                   "attachment_staging_bytes", "attachment_project_staging_bytes", "attachment_staging_seconds", "attachment_bytes",
                   "native_link_count", "native_link_history_revisions", "native_link_write_receipts", "native_link_metadata_bytes")} |
                   {"event_replay_seconds": 7 * 86400 if event_features else 0},
        "adapter_protocol": "acs-adapter/1", "event_protocol": "acs-event/1"})
    app.state.oauth_provider = provider
    return app
