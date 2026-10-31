# Agent Collaboration System v1.5.0

2026-10-13

ACS v1.5.0 connects an owner's durable project collaboration, native
Codex/OpenCode execution and current machine files through the Runtime MCP
surface. Agents can coordinate work, continue after disconnects, operate files
on connected machines and review the exact source and evidence returned.

## Owner collaboration

New single-owner installations use `access_mode: owner`. Operations check trusted
credentials, tenant/principal and Authority identity, active service and target
objects, explicit revocation, request deduplication and expected revisions.
Project, Machine, Node, Connection and Endpoint registrations persist until an
explicit lifecycle change. Execution reads the current process, transport and
native Session before dispatch.

Teams bind AgentSlots, principals, duties and Harness requirements. Root and
Route describe project and development-line responsibility; Task Agent remains
the proposed task-level collective term. Engineer, Reviewer, Specialist and
Finalizer describe duties. Independent reviewer assignment and candidate-specific
acceptance checks retain the exact Source, Artifact, Evidence and Review
identities.

Native Codex and OpenCode run in the selected user's environment, using its
tools, MCP servers, plugins, project configuration, provider, models and approval
configuration. Attached Session read, send and cancellation use the installed
native API; process termination requires verified ownership. Interactive
approval support depends on the actual native client handler and its readback.

Shared mode remains available with per-subject Grants, Policies, Profiles and
budgets. An unspecified existing configuration retains shared behavior until
guided adoption selects the owner strategy. See the
[owner contract](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.5.0/docs/runtime/OWNER-RUNTIME.md).

## Durable messages and continuation

Async submission returns committed Message, response and notification handles.
Sync sends and response waits observe the selected condition, with an optional
caller timeout. Interrupted waits and disconnected clients retain durable
tracking; Agents can resume with the same handles or read Inbox.

Owner requests remain valid while service, initiating identity and targets are
active. An optional business deadline bounds the request when selected.
Configured Temporal delivery maintains committed work and retries remote
readiness and connection checks. Signed terminal response readback verifies
digests and stores native results in the Core Artifact cache, including recorded
historical responses. See the
[Send/Wait lifecycle](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.5.0/docs/runtime/SEND-WAIT-LIFECYCLE.md).

## Machine filesystem service

Owner tools provide `read_file`, `list_directory`, `glob`, `grep`,
`write_file`, `edit_file` and `apply_patch`. Only `path` is required for
`read_file`. `filesystem_context` discovers the actual machine, account,
platform, home, working directory and connected choices; `select_filesystem`
sets this MCP connection's default. Every file action accepts optional
`machine_id` and `cwd` for one call.

Files follow the selected OS account's permissions, including hidden, ignored,
untracked and paths outside repositories, large files and binaries. Text and
Base64 reads, listings and searches paginate with `complete` and
`next_cursor`, preserving the original machine, path and query.

Local uses Core's OS account. SSH runs an installed fixed file service. Registered
Nodes use pinned TLS, signed identity, owner authorization, explicit revocation
and request journaling. File requests run directly through these services;
readiness is independent of native Harness Session activity. The
[machine filesystem guide](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.5.0/docs/runtime/MACHINE-FILESYSTEM.md)
covers ranges, writes, patches, continuation and uncertain-write readback.

## Source observations and versions

SourceBinding supplies repository, location and version guidance so Agents can
choose an available machine, native tool, Git or repository reader. Current
product Source reads resolve the repository's physical primary worktree and
observe its actual branch and edits. `read_source_file`, `list_source_files`,
`search_source_files`, `read_source` and `read_diff` retain Project Source
semantics and explicit captured-version selection.

Source readbacks report the actual provider, root, commit, tree,
`view_revision` and observation time. Product Source and Management Root
observations have their own fields; pagination retains the captured view.
Shared mode retains its established Source schemas, permissions and version
checks. Review and acceptance retain the actual candidate and Evidence.

## Installation, upgrades and recovery

Give the
[v1.5.0 Release](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.5.0)
to Codex or OpenCode. The Agent verifies the standalone `acs_bootstrap.py`
against `SHA256SUMS.txt`, previews the chosen local Linux, SSH or WSL target,
and installs with `--version v1.5.0` using the observed machine/account/home
binding. It executes setup and verification commands and configures selected
clients. The owner chooses placement and completes required system or account
authorizations.

New installations enable automatic upgrades by default; regular upgrades
preserve an existing opt-out. Stable MCP startup restores the existing owner
Core services. Configured private SSH and Secure MCP Tunnel profiles supervise
their owned processes and recover connections. Reports identify the actual
scheduler, startup state and service/connection readbacks.

The changed Runtime schema and MCP catalog make v1.5.0 an AI-guided upgrade
for existing installations. Preserve projects, Root/Route and Source identities,
configuration, credentials and keys, deduplication, recorded evidence, explicit
revocation and rollback data. A positively identified private Root installation
can adopt owner mode with a configuration backup; explicit shared deployments
retain their selected mode. Receiver owner/native adoption updates its signed
Endpoint registration and matching process configuration together, then restarts
and reads back the actual binding and mode.

Reconnect Codex/OpenCode after activation and verify `tools/list`,
`read_profile`, `list_projects`, `filesystem_context` and intended
`load_project` context. For enabled ChatGPT web access, restart the configured
Tunnel/MCP process, select **Refresh** on the existing connection in ChatGPT
Plugins, inspect the tool metadata and start a new chat. Account actions use the
owner's external browser on the client machine, with required login, permissions,
secret entry and connection consent completed by the owner. Follow
[getting started](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.5.0/docs/GETTING-STARTED.md)
and
[automatic upgrades](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.5.0/docs/AUTOMATIC-UPDATES.md).

Release ZIP/TAR assets include a source-bound manifest and SHA-256 inventory.
The distribution is v1.5.0; setup Skill v0.4.0 and Runtime package v0.1.0 retain
their independent versions. The project uses
[Sustainable Use License 1.0](https://github.com/D1ChangGeng/Agent-collaboration/blob/v1.5.0/LICENSE).
