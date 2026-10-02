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

## Select and prepare the connection

During machine setup, the Agent asks whether to enable ChatGPT web now, use
local clients only, or configure web later. Record `enable`, `skip` or `later`
with Bootstrap's `--chatgpt-web` option. For a deferred connection, invoke the
setup Skill with "Connect this ACS installation to ChatGPT web."

For `enable`, perform preparation on the confirmed Linux Runtime host. An SSH
or WSL client executes the following helper on that host:

```text
python scripts/acs_web_setup.py --choice enable --runtime-root <active-release-directory> --installation-root <installation-root> --config <private-surface-config> --json
```

The helper generates a read-only plan containing the exact ACS stdio command,
AI steps, owner actions and setup prerequisites. Once selected, add
`--tunnel-id <id>` to produce the Tunnel command arguments. The AI uses its
native execution tools to perform these steps and verify their results.

For a managed installation, use the absolute installation root, active Release
directory and private surface config recorded in its state. The optional
`--installation-root` verifies this binding and selects the stable
`acs_launcher.py` command for the Tunnel. New MCP processes then follow the
active version after upgrade or rollback; a running process retains its version.
A standalone verified Release uses `--runtime-root` with its version directory
command.

When upgrading an existing Tunnel connection, regenerate this plan and apply
its MCP command to the selected profile through the installed client's supported
configuration flow. Retain private credential references and verify the profile
after reconnecting.

First validate the configured principal, Profile, Grant expiry/revocation and
actual `read_profile` and `list_projects` through that stdio process. Project
registration may follow later; an empty list is a valid initial result.
`load_project` becomes required for each adopted project.

## Owner account actions

The Agent fetches the linked official instructions at setup time, checks account
and workspace availability, then explains these owner actions with the current
page labels:

| Action | Where and expected result |
| --- | --- |
| Select the account context | In Platform Tunnel settings, select the intended organization and associate the target ChatGPT workspace. |
| Confirm permissions | Organization owner/RBAC admin grants Tunnels Read + Manage for creation and Read + Use for operation/selection; workspace policy allows developer mode. |
| Select a Tunnel | Create or choose the owner's Tunnel and give the Agent its non-secret `tunnel_id`. |
| Provision the runtime key | Put the key in private Runtime-host storage used by `CONTROL_PLANE_API_KEY`; the Agent records the reference and checks availability. |

The Agent provides the current Platform Tunnel settings link from its generated
plan and confirms the selected organization/workspace with the owner. A
successful key-entry step reports the private storage reference, never its value.

The current permission and association rules are documented in the
[official Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
Keep keys out of chat, CLI arguments, Git, logs and installation reports. ACS
and the Tunnel use separate credential references. The Agent prepares private
storage and service configuration; the owner completes required login,
permission and secret-entry confirmations.

## AI configuration and service verification

On the selected Runtime host, the AI installs the current Tunnel client using
the official download route, checks its version and supported flags, then
executes the helper's exact commands. The command structure is:

```text
tunnel-client init --sample sample_mcp_stdio_local --profile acs-private --tunnel-id <id> --mcp-command <exact-ACS-stdio-command>
tunnel-client doctor --profile acs-private --explain
tunnel-client run --profile acs-private
```

The official [Tunnel client setup](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#set-up-tunnel-client)
describes these commands. Keep the client running during connection and use its
health/readiness endpoints for readback. Configure an owner-local supervised
service when supported, with private environment storage, bounded log retention,
restart behavior and rollback references. Report unavailable persistence as a
specific remaining step. The AI performs installation, configuration and
diagnostics; executable plans become evidence only after execution.

## Owner ChatGPT confirmation

After Tunnel health is observed:

1. Open ChatGPT **Settings → Security and login**, then enable **Developer mode**
   when the account/workspace allows it.
2. Open **ChatGPT Plugins**, choose **+**, name the connection, select
   **Connection → Tunnel**, and select or enter the same `tunnel_id`.
3. Create the connection and review its discovered tools. In a new conversation,
   add that connection from the tools menu.

The current [ChatGPT connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt)
documents these confirmation steps. If the UI differs, the AI checks that page
and the account's supported flow before giving updated instructions.

Give the new ChatGPT conversation this verification request:

> Use the ACS connection to call read_profile and list_projects. Explain my
> current Profile, visible tools and projects. If no project is registered,
> explain how to start project setup. If a project is registered, load that exact
> project and report its current context and SourceBinding.

The Agent records actual web tool results. Once the owner authorizes a bounded
project write, read back its WorkItem, Route or Message. Verify a denied operation
under a narrower Grant, disconnect/reconnect behavior and permission revocation
using an isolated test Grant. Keep the active owner installation recoverable.

## Connection report and recovery

Record the web choice, Runtime-host identity, Tunnel identifier, credential
references, Profile/Grant, local MCP readback, Tunnel health, web tool readback,
service persistence and exact pending owner actions. A prepared plan, healthy
Tunnel and verified ChatGPT connection are separate observed states. An
unfinished connection retains its resume command and next action.

For discovery failures, check the running Tunnel service and its diagnostics,
then follow the official guide's permission/workspace checks. For tool denials,
inspect the ACS principal, Profile and Grant. After tool metadata changes,
refresh the ChatGPT connection and repeat readback. Project context errors
follow [project adoption](PROJECT-ADOPTION.md) and Source registration validation.

Official index: [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels),
[ChatGPT connection](https://developers.openai.com/plugins/deploy/connect-chatgpt),
[authentication](https://developers.openai.com/plugins/build/auth), and
[documentation discovery](https://developers.openai.com/llms.txt). The shared-user
authentication boundary is described in the authentication guide; this ACS
profile uses the installation owner's scoped Domain authority.

This profile supplements the authenticated remote HTTP resource-server profile
in the repository's [PROJECT-HTTP.md](https://github.com/D1ChangGeng/Agent-collaboration/blob/main/docs/runtime/PROJECT-HTTP.md).
Both use the same Domain authorization
and project tool contracts. A product acceptance record names the exact profile
and observed client path.
