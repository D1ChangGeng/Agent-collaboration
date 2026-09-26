# Project MCP HTTP resource server

`acs-project-runtime --transport streamable-http --http-config <path>` serves
the same PostgreSQL-backed typed project tools as stdio. The normal surface
configuration and catalog arguments remain required. Stdio requires `--profile`;
HTTP rejects that flag and selects Profiles only from explicit OAuth bindings. No schema,
project, Grant, public listener, tunnel or account connection is provisioned
by starting this process.

The backend is loopback-only. An operator must separately admit and verify an
HTTPS ingress or secure tunnel to `/mcp`. `resource_url` is the exact external
HTTPS resource identifier; issuer and introspection endpoints must also be
explicit HTTPS URLs. The server does not discover or follow token-supplied URLs.
Proxy headers do not alter authentication or addressing. Host and Origin checks
are enabled; browser CORS is limited to exact configured origins.

## OAuth and Domain authority

The deployment is an OAuth **resource server**. An external Authorization Server
owns authorization, consent, exact client callbacks, PKCE, token issuance and
revocation. The MCP SDK supplies RFC 9728 protected-resource metadata and the
HTTP 401 discovery challenge. The server uses authenticated RFC 7662
introspection to verify active state, issuer, exact audience, expiry, subject,
client ID and scopes. This profile requires those claims even when the base RFC
makes a field optional. Introspection credentials are private references; access
tokens never enter tool input, output, Domain payloads or access logs.

An operator binding maps `(issuer, subject, client_id)` to an **existing** Domain
principal, Grant and Profile. Multiple bindings share one endpoint. They remain
inside the configured tenant and authority incarnation. A token cannot choose a
Profile, enlarge a Grant, enroll a principal or grant project membership.
The required connection scope is `acs:connect`. Each tool additionally requires
all its catalog `security_scopes`. Discovery is the intersection of implemented
tools, configured Profile, OAuth scopes and current Domain project authority.
`read_profile` reports both the Domain Grant and the transport scope boundary.

Introspection runs on every HTTP request. Active notification publishers refresh
it at a bounded interval (default five seconds; configurable one to five).
Expiry and the observation-age bound are strict. Network failure, inactive
tokens, changed subject/client binding, insufficient scope, revoked Grants or
retired notification Sessions suppress further wakes. Grant and project checks
still run against the Domain at every protected read or mutation. A refreshed
token may continue the same OAuth principal and Domain role; a different
principal cannot borrow its MCP Session. Inbox state survives reconnects.

## Configuration shape

```json
{
  "schema_version": "acs-project-http/1",
  "issuer_url": "https://identity.example.com",
  "resource_url": "https://acs.example.com/mcp",
  "introspection_url": "https://identity.example.com/oauth/introspect",
  "introspection_client_id": "acs-resource-server",
  "introspection_secret_ref": {"kind": "environment", "name": "ACS_INTROSPECTION_SECRET"},
  "bindings": [{
    "subject": "operator-issued-subject",
    "client_id": "registered-web-client",
    "principal_ref": "principal:manager",
    "grant_ref": "grant:manager",
    "profile": "root_manager"
  }],
  "allowed_origins": ["https://web.example.com"],
  "authorization_refresh_seconds": 5
}
```

These names are configuration examples, not deployed identities or endpoints.
The current tests exercise real loopback HTTP, SDK Sessions, PostgreSQL and
revocation/Inbox recovery with a fixture introspection service. They do not
establish an admitted HTTPS/tunnel deployment, completed user consent, a web
SaaS connection, or a live Codex/OpenCode workflow Gate.

References: [MCP authorization](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/authorization/index.mdx),
[RFC 7662 introspection](https://www.rfc-editor.org/rfc/rfc7662.html),
[RFC 9728 resource metadata](https://www.rfc-editor.org/rfc/rfc9728.html).
