# Single-user private Tunnel profile

This P2 profile connects one installation owner's ChatGPT developer-mode app to
that owner's Linux ACS project MCP process. A Windows Harness may act as the
client while the Source/CAS service remains on the admitted Linux host. The
local process uses the existing
`acs-project-runtime` stdio transport, a configured `root_manager` or narrower
Profile, and an existing Domain principal and Grant. ACS checks the Grant at
each protected operation. The OpenAI Secure MCP Tunnel carries the private MCP
connection through an outbound client; it does not make the local service a
public listener.

The installation owner controls the Platform organization, ChatGPT workspace,
Tunnel association, tunnel runtime key, local ACS process and its credential
reference. This profile is admitted for a single owner context only. The fixed
stdio credential represents that owner; it cannot identify distinct users who
share the same Tunnel or app. The installer must keep the credential in a private
file or process environment, bind a bounded Grant, and withhold a shared-team
configuration. Sharing requires a separately reviewed per-user authentication
profile.

## Setup and verification

1. The setup Agent verifies the local Runtime, Source and project registration,
   Profile, Grant expiry and revocation state, and `read_profile`, `list_projects`
   and `load_project` over the exact stdio command it will give the Tunnel.
   A `local_services_ready` installation receipt is only the entry to this
   readback; it does not authorize the Tunnel connection by itself.
2. The installation owner creates or selects a Tunnel in OpenAI Platform,
   grants the required Tunnel permissions, supplies the runtime key through the
   platform's private mechanism, and enables ChatGPT developer mode when the
   account permits it. The Agent may configure and diagnose the local
   `tunnel-client` after these owner actions.
3. The owner connects the Tunnel in ChatGPT. The Agent checks the current
   official setup documentation and explains the page actions shown at that
   time. The Agent verifies the app's discovered tool set and then reads the
   exact adopted Project from ChatGPT.
4. The owner authorizes a bounded real-project write workflow. Read back the
   resulting Route, WorkItem or Message from ACS and the project source where
   applicable. Test a denied operation under a narrow Grant, Tunnel disconnect
   and reconnect, and Grant revocation. Record current Tunnel, app, Runtime,
   source and credential-scope identities without storing secret values.

Official references: [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels),
[ChatGPT connection](https://developers.openai.com/plugins/deploy/connect-chatgpt),
[MCP authentication](https://developers.openai.com/plugins/build/auth), and
[documentation index](https://developers.openai.com/llms.txt).

This profile supplements the authenticated remote HTTP resource-server profile
in [PROJECT-HTTP.md](PROJECT-HTTP.md). Both use the same Domain authorization
and project tool contracts. A product acceptance record names the exact profile
and observed client path.
