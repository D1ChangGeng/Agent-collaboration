# Get started with Agent Collaboration System

Give the [repository link](https://github.com/D1ChangGeng/Agent-collaboration)
to a local Codex or OpenCode session and ask it to guide the installation.
The Agent inspects your operating system, active Harness and existing ACS
setup. You choose the Runtime machine, the client hosts that should connect,
and whether to enable ChatGPT web now, use local clients only, or configure web
later. The Agent probes those targets and executes installation, client setup,
diagnostic and verification commands. You complete required system or account
approvals. Project setup is available when you are ready to start a project.
For web setup, account pages use your external browser on your client machine.
You confirm required login, permissions, secret entry and connection consent.

## Agent launch request

Use the [v1.5.2 Release](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.5.2)
and its `acs_bootstrap.py` asset for this machine selection flow.
The default Bootstrap version is `v1.5.2`. Existing installations use the verified
v1.5.2 Bootstrap for an AI-guided upgrade through the v1.5 Runtime schema and
MCP catalog transition. The Agent previews the transition, preserves identity and
configuration, and verifies the activated access mode and connections. See the
[release notes](RELEASE-NOTES-v1.5.2.md).

For a fresh machine, use the standard Release Bootstrap shipped with that
Release before project setup:

```text
Download the acs_bootstrap.py asset and SHA256SUMS.txt from the selected GitHub
Release. Verify the Bootstrap digest before running it. Confirm the
Runtime host and client hosts, ask whether ChatGPT web should be enabled now,
skipped or configured later, probe the chosen Runtime host read-only, and
preview installation. Verify SHA256SUMS.txt and the release manifest, bind apply
to the observed machine identity, and configure the selected clients. Execute
the setup and verification commands. Report the machine/account binding, version,
actual access mode, services, filesystem context and actual MCP readback.
```

> Use this repository as the ACS distribution source. Inspect its current
> release and installation instructions. First confirm whether the Runtime
> should run on this Linux machine, a named remote SSH host, or a named WSL
> distribution, and which Codex/OpenCode client hosts should connect. Ask whether
> to enable ChatGPT web now, use local Harnesses only, or configure web later. Install
> the verified package on the chosen host, configure the selected clients and
> validate actual MCP calls. Ask me for the machine choice and required
> authorizations. Complete the selected web setup and explain the required
> owner page actions in my external browser on my client machine using my setup
> authorization, or provide exact steps for me to
> complete and confirm. Report verified connections and available capabilities. I will
> use the setup Skill to initialize projects when ready.

## Select the Runtime machine

The installation has two placements: the Linux host running ACS services and
the host(s) running client Codex/OpenCode sessions. They can be the same machine
or separate machines. The Agent first confirms the intended placement:

| Runtime choice | Target information | Client connection |
| --- | --- | --- |
| Local Linux | This host and observed owner account | Local stdio MCP process |
| Remote Linux through SSH | User-selected SSH target and observed login account | SSH stdio MCP process descriptor |
| WSL | User-selected distribution and observed Linux account | WSL stdio MCP process descriptor |

If the choice is missing, the Agent asks one question covering local Linux,
remote SSH or WSL and the corresponding target. Existing SSH aliases,
installation records and project directories help discovery; the user's
placement choice determines the installation destination. The current Harness
can be the client default when it matches the user's intended use; additional
client hosts or Harnesses are confirmed before configuring them.

After selection, the Agent probes that exact host read-only to establish machine
identity, account, home directory, Linux support, SSH/WSL reachability and
prerequisites. It pins the full machine identity, account and home directory
before directory or service writes and shows the planned changes before apply.
Authorization prompts and account login remain user actions when the platform
requires them.

The Bootstrap destination arguments are `--runtime-host local|ssh|wsl`,
`--ssh-target` and `--wsl-distribution`; `--harness codex opencode` selects
clients. Supply the preview's `--expected-machine-id`, `--expected-account` and
`--expected-user-home` before apply to bind the full Runtime host identity. The
bounded Linux installer `scripts/acs_install.py` requires `--host-confirmed`.
The Agent executes commands from the chosen verified Release, previews changes,
and preserves the installation and MCP configuration rollback data.

SSH and WSL install Runtime services and owner Authority with `--runtime-only`.
The Bootstrap returns a caller-side stdio descriptor; the Agent installs setup
and knowledge Skills and configures MCP on each selected client host. Select
the Runtime host as a client when you also want a Harness connection and Skills
there. Local Linux defaults to client setup on the same host; `--runtime-only`
selects a service-only installation. Global Runtime setup executes with an empty
project list and can be followed by project setup at any time.

## Choose ChatGPT web access

After machine selection, the Agent asks for an explicit web choice when your
request has not supplied one:

| Choice | Setup behavior |
| --- | --- |
| Enable now (`enable`) | Prepare a private Tunnel connection and guide the required owner account actions, then verify ChatGPT tools. |
| Local clients only (`skip`) | Install the selected Codex/OpenCode clients and record their verified connection scope. |
| Configure later (`later`) | Finish machine setup and include the web setup resume entry in the report. |

Bootstrap receives the choice with `--chatgpt-web enable|skip|later` and accepts
`--tunnel-id` once selected. A generated web plan identifies the Runtime command,
AI execution steps and owner actions. Its presence records preparation; the
Agent reports web readiness after Tunnel health and ChatGPT calls are observed.
Projects can be registered after either machine or web setup.

## Verify the machine installation

The Agent uses `scripts/acs_doctor.py` and actual service readback on the Runtime
host. For SSH or WSL it configures clients on their own hosts with the Bootstrap
stdio descriptor and each client's configuration mechanism. A descriptor is
connection setup data; actual readiness comes from the client's handshake.
It verifies `tools/list`, `read_profile` and `list_projects` from every selected
client. Record the actual `access_mode` and discovered input schemas. For owner
access, also read `filesystem_context` to confirm the service machine, OS account,
home and working directory.
An empty project list is a valid new installation. Project-specific
`load_project` readback follows project registration.

The Source/CAS backend requires Linux. Windows clients use a confirmed remote
Linux host or named WSL distribution and receive their own connection readback.
Owner credentials stay in private storage on the Runtime host. Machine binding
describes installation placement and transport; Node enrollment, execution
placement and cross-host dispatch are verified through their Runtime mechanisms.

The local installer reports `local_authority_ready` after the Python environment,
PostgreSQL, Temporal and private owner Authority are checked. Selected clients
receive their own setup and knowledge Skills and MCP configuration. The Agent
reports client readiness after actual MCP calls pass and explains available
tools and the optional project setup step.

## Configure owner startup recovery

Stable MCP startup restores the recorded owner Core services and requests
configured SSH and web recovery independently. On a Windows client using WSL,
the Agent also runs `scripts/acs_windows_startup.ps1` from the verified Release
or its verified installed setup Skill payload under the installing Windows
account. This helper targets Windows x64 and requires WSL, the Task Scheduler
PowerShell cmdlets and the installed 64-bit .NET Framework C# compiler.
The Agent checks these prerequisites before apply. It uses the confirmed
`-WslDistribution`, `-RuntimeUser`, `-LinuxInstallationRoot` and full
`-ExpectedMachineId` from the Runtime probe. The default invocation previews
the task; `-Apply` installs or migrates it and `-Check` reads back its startup
state. The Bootstrap's `client_connection.background_startup` object supplies
the script source, this parameter binding and preview/apply/check sequence; the WSL stdio entry also selects the
recorded Linux account explicitly. An installation with `startup.enabled=false`
returns `owner_disabled`. The GUI host keeps the selected WSL recovery process
in the background and passes its exit code to Task Scheduler.

The Agent verifies the Runtime's actual Docker init mechanism, the task's
owner/action, PostgreSQL and Temporal, each configured transport, and MCP
calls through every selected client. A Docker backend diagnosis reads the
daemon's actual data root and checks the preserved ACS container store.
A repair plan that changes shared Docker/containerd services requires explicit
authorization and a new private backup directory before apply.
See [owner startup recovery](runtime/STARTUP-RECOVERY.md) for commands, existing
task adoption and component diagnostics.

## Owner collaboration and machine access

New single-owner installations use `access_mode: owner`. Operations check trusted
credentials, tenant/principal and Authority identity, active service and objects,
explicit revocation, request deduplication and expected revisions. Machine, Node,
Connection and Endpoint registrations persist until an explicit lifecycle change.
Execution reads actual process, transport and native Session readiness. Native
Codex/OpenCode use the selected user's tools, MCP servers, plugins, project
configuration, provider, models and approval settings. Interactive approval
requires the actual native client handler and response readback.

Owner machine tools operate under the connected OS account. Call
`filesystem_context` to discover machines and directories; `select_filesystem`
sets this MCP connection's default. `read_file` requires only `path`;
`list_directory`, `glob`, `grep`, `write_file`, `edit_file` and
`apply_patch` provide discovery, search and changes. All accept optional
`machine_id` and `cwd` for one call. Local uses Core's account and home;
SSH uses an installed fixed service, and registered Nodes use pinned TLS,
signed identity, owner authorization and request journaling. Their file service
readiness is independent of a native Harness Session's busy state.

OS account permissions govern hidden, ignored and untracked files, paths outside
repositories, large files and binaries. Continue paginated results with their
`next_cursor` until `complete=true`, retaining the original machine and path.
Use the [machine filesystem guide](runtime/MACHINE-FILESYSTEM.md) for file
ranges, changes and recovery. Shared deployments retain their configured
Grants, Policies, budgets and Source interfaces; the
[owner contract](runtime/OWNER-RUNTIME.md) describes each access mode.

## Automatic upgrades

New installations enable automatic upgrades by default.
The Agent records the actual scheduling backend and state: an active same-owner
systemd user timer, a registered cron entry or background catch-up checks on new
MCP connections. Host sleep and user manager availability affect scheduled
checks. The updater checks stable Releases daily and retries errors after an
hour, using the existing machine/account/home binding, Harness selection and
web settings.

Use `--no-auto-update` during installation to opt out or `--auto-update` to
enable it explicitly. A regular upgrade preserves an existing disabled setting
when neither flag is supplied. After installation, the
installed Bootstrap accepts `--set-auto-update on|off|status`.
`--update --force-check` checks immediately; add `--apply` to activate an
eligible update. Automatic updates require the same major version and unchanged
license, schema, migration, provider and MCP catalog contracts. A changed contract
requires explicit review.

Stable launcher commands follow the active version for future local, SSH, WSL
and Tunnel MCP processes. Existing sessions continue on their running version.
ACS verifies the new environment, provider health and existing authorization
before activation and retains the previous version for rollback. Stable startup
restores the existing owner Core services; configured private SSH and Tunnel
profiles supervise their processes and recover connections. Read back their
actual health after startup. Owned local Skills refresh with the upgrade;
Skills on separate client hosts are refreshed through client setup maintenance.

Existing installations use the verified v1.5.2 Bootstrap for the schema/catalog
transition. The Agent preserves project and Root/Route identity, configuration,
credentials, keys, explicit revocation and rollback data. It verifies the actual
mode and separately updated Receiver configuration. Reconnect Codex/OpenCode
after activation; for ChatGPT, restart the configured Tunnel/MCP process,
select **Refresh** on the existing connection in ChatGPT Plugins and start a
new chat. Read [automatic upgrades](AUTOMATIC-UPDATES.md) for the full transition,
controls, status meanings and rollback procedure.

## Start a project

For an existing project, the Agent first inspects the active session's checkout,
Management Root manifest and authorized existing SourceBinding metadata. It
probes relevant local, SSH or WSL paths with
`scripts/acs_source_discovery.py --include-untracked` and identifies the actual
Source machine, account, repository root, Project/Root identity, commit/tree and
working tree. Several clones may exist; the Agent compares their observed
revisions before choosing a registration view. It asks for a source host/path
only when that information or access remains unresolved. Follow
[Source discovery](runtime/SOURCE-DISCOVERY.md) for the complete procedure.

Invoke the installed `agent-collaboration-setup` Skill when you want to use ACS
for a project. It asks for the project location and collaboration goal at this
point, inspects existing state, and creates or adopts the Management Root inside
the project source checkout. It preserves Root/Route identities, project
instructions and knowledge. Use the exact confirmed Runtime connection and
reviewed Source scopes when registering the project. The identity and Source
registration procedures are in
[Runtime project adoption](runtime/PROJECT-ADOPTION.md).

SourceBinding supplies repository, location and version guidance. Record the
product Source through `primary_source_id` and its preferred repository location
through `primary_source_root`. Current owner Source reads resolve that
repository's physical primary worktree, observe its actual branch and edits,
and report `actual_source`. An explicit `source_root` selects another configured
readable worktree; an explicit `revision` selects captured bytes.
`read_source_file`, `list_source_files`, `search_source_files`,
`read_source` and `read_diff` retain these Source semantics. Pagination uses
the returned `view_revision`; the Agent records the reader and actual source
used for Review and Evidence.

For a linked Git worktree read through the Source service, locate and authorize
its Git control directory and common object directory. The service checks both
through pinned directory handles. Verify that `AGENTS.md` and the manifest carry
the same `project_id`, then inspect `load_project` product Source and Management
Root observations before reporting project readiness.

After setup, open Codex or OpenCode with the
Management Root as its working directory. The Root Agent reads its `AGENTS.md`,
project identity and Route registry. Tell it the collaboration goal and ask it
to create the first Route and Team.

For a first collaborative task, ask the Root Agent to create a WorkItem, hand
the work to an authorized AgentSlot, inspect the message receipts, wait for a
response or recover it from Inbox, then request an independent Review of the
resulting evidence. The Agent should report exact source commit and tree,
delivery state, reviewer identity, unresolved items and the next authorized
action before accepting work.

## ChatGPT web connection

For `enable`, follow the [private Tunnel runbook](runtime/P2-PRIVATE-TUNNEL-PROFILE.md).
The Agent prepares the Tunnel on the confirmed Runtime host. Account pages use
your external browser on your client machine:

1. Verify the exact ACS stdio command, actual access mode and owner identity;
   generate the plan with
   `scripts/acs_web_setup.py --choice enable --runtime-root <release-directory>
   --config <private-surface-config> --json`.
   For a managed installation, add `--installation-root <installation-root>`
   with its active Release directory and matching private config. The helper
   verifies that binding and emits the stable launcher command for the Tunnel.
   A standalone verified Release uses its version directory command.
2. Fetch the current official instructions linked in the runbook. Explain the
   required owner permissions, private-key provisioning and connection page
   actions, including how to recognize completion.
   Documentation searches and fetches are read-only and can proceed independently.
   The Agent verifies actual OS or external browser control in its current
   Harness and navigates account pages within your given setup authorization,
   seeking further authority only when the intended operation requires it.
   You confirm
   required login, permissions, secret entry and connection consent. If control
   is unavailable or you prefer to act yourself, it provides official links,
   exact pages and current labels, actions and expected results, then waits for
   your completion before dependent setup and verification.
3. Install and configure the Tunnel client, execute its diagnostics, and keep
   its runtime service healthy. The Agent executes commands; the owner completes
   required authorization and confirmation steps.
4. Verify tool discovery, the actual mode in `read_profile` and `list_projects`
   from ChatGPT. For owner access, verify `filesystem_context` and a selected
   path read. Start with an empty project list when appropriate; after project
   setup, verify `load_project` and a bounded authorized write. Following a
   schema upgrade, select **Refresh** on the existing connection in ChatGPT
   Plugins, inspect the current metadata and use a new chat for verification.

To resume a deferred choice, tell the setup Skill: "Connect this ACS installation
to ChatGPT web." It inspects the current connection before applying the same
route and records each remaining owner action in the installation report.

## Installation report

Ask the Agent to report these observed facts after setup:

| Area | Readback |
| --- | --- |
| Runtime placement | Local/SSH/WSL target, machine identity, hostname and owner account |
| Distribution | Release tag, version, commit, tree and distribution digest |
| Services | PostgreSQL, Temporal, Core/MCP health, configured delivery worker and startup recovery readback |
| Access | Actual owner/shared mode, tenant/principal and Authority identity, active state, explicit revocation and visible schemas; configured Grants/Policies for shared |
| Harnesses | Client hosts, selected user/environment, native version, tools/MCP/plugins/approval configuration and actual connection readback |
| Machine files | Selected machine, OS account, platform, home/cwd, available Local/SSH/Node choices and a current file read |
| ChatGPT web | Explicit `enable`/`skip`/`later` choice, Tunnel identity and health, ChatGPT discovery/readback, exact pending owner actions and resume entry |
| Automatic upgrades | Enabled policy, actual scheduler backend/state, connection catch-up, last result and next eligible check |
| Recovery | Active/previous version, configuration and key references, preserved revocation state, Windows/WSL task binding and running state where selected, component health, restart/reconnect result and rollback references |
| Projects | Current project list; after setup, `project_id`, Management Root, Routes, SourceBinding guidance and actual product/management Source observations |
| Next action | Optional project setup through the installed Skill; for a ready project, Root Agent directory and prompt |

The report distinguishes installed files, configured connections and observed
runtime behavior. For setup problems, use the diagnostic output and the
[troubleshooting guide](TROUBLESHOOTING.md).

## Installation state and rollback

The Release Bootstrap stores versioned files in the user data directory and
maintains `state.json` with the active version, previous version, source commit
and source tree. A failed archive or installer step leaves the active version
unchanged. A verified automatic or guided upgrade can switch the active version;
the previous version remains available for rollback. The Agent verifies service
and selected-client MCP readback after activation. Project Source registration
has its own identity and context validation.
Manual rollback records the rejected version in `held_version` for explicit
review before the updater applies that same version again.

## Installation verification scope

Use the install receipt and one real MCP connection per selected client for
`tools/list`, `read_profile` and `list_projects`. Project initialization then
verifies its own `load_project` context. Capability knowledge comes from the
catalog and Skills; project operations are exercised when that workflow begins.
See [installation verification and timing](INSTALLATION-PERFORMANCE.md).

For messaging, async returns committed Message, response and notification
handles; sync waits for the selected condition, defaulting to the final response.
Optional caller timeouts return pending handles and retain tracking. Owner
requests stay valid while service, identity and targets are active, with an
optional business deadline. Shared validity follows configured Policy, Grant
and budget horizons. See [Send/Wait lifecycle](runtime/SEND-WAIT-LIFECYCLE.md).

## Agent responsibility and duties

Use Root/Route to describe project/development-line responsibility. Task Agent
is the proposed task-level collective term; select Engineer, Reviewer,
Specialist or Finalizer duties through authorized team configuration. Read the
[organization model proposal](runtime/AGENT-ORGANIZATION-MODEL.md) and the
actual `load_project.actor_binding` / `list_collaborators` facts. Verify the
current Slot, Scope, Profile, Grant and Work association before delegation.
