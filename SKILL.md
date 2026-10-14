---
name: agent-collaboration-setup
description: Manage ACS machine and project setup. Install, configure, validate, repair, upgrade, or safely remove ACS on a confirmed local Linux, SSH, or WSL Runtime host; connect Codex and OpenCode client hosts; separately bootstrap or adopt ACHP project Management Roots and Routes. Use when the user explicitly asks to set up or change the collaboration mechanism itself. Workspace removal is guarded until ownership is reviewed.
license: Sustainable Use License 1.0
metadata:
  version: "0.4.0"
  scope: "machine-and-project-setup"
  protocol: "ACHP"
---

# Agent Collaboration Setup

This Skill guides two setup lifecycles: an owner account's ACS machine
installation and a project's Management Root. New single-owner Runtime
installation records access_mode=owner. Global installation establishes
the selected Runtime host and client connections. Project setup can follow
later when the user invokes this Skill for a project. The preferred Management
Root is nested in the project's Git repository. Owner project registration also
supports Management Roots in other authorized directories and records the
machine and directory of their current files.

After setup, ordinary collaboration proceeds through project `AGENTS.md`,
`.agents/`, knowledge Skills and MCP tools. Invoke this Skill for installation,
connection or project setup maintenance.

## Agent operating guide (read before choosing a lifecycle)

When the user describes a goal in ordinary language, first read
[references/OPERATING-GUIDE.md](references/OPERATING-GUIDE.md). It defines the
Root/Route/Session/Endpoint mental model, the observe-before-ask sequence,
minimum interview rule, natural-language intent mappings, lifecycle boundaries,
and the exact point where the current Skill has no mechanism. Use the
support-status vocabulary there rather than turning a design possibility into a
capability claim.

Use the supporting ledgers when you need a precise boundary or regression
case:

- [references/CAPABILITY-MATRIX.md](references/CAPABILITY-MATRIX.md) records
  instruction, decision, mechanism, validation, evidence, and current status
  for each capability.
- [references/SCENARIO-MATRIX.md](references/SCENARIO-MATRIX.md) records the
  representative Root, Route, topology, continuity, UX, safety, and
  finalization scenarios.

The references are decision aids, not a replacement for observed filesystem,
Git, or Harness facts. Read only the reference needed for the current request.

## Use this skill only for

- Global ACS installation, validation, repair, upgrade or removal on a confirmed
  Runtime host, and configuration of the selected client Harness connections.
- `bootstrap`: initialize ACHP in a new/blank repository.
- `adopt`: add ACHP to an existing repository without replacing existing project guidance.
- `upgrade`: update ACHP-managed protocol/template files while preserving project-owned state.
- `repair`: restore missing ACHP-managed setup files.
- `validate`: verify the ACHP installation and routing.
- `uninstall`: remove ACHP-managed repository setup while preserving project
  knowledge by default. The Workspace form is currently guarded; see the
  Workspace schema boundary below.

## Global machine installation

1. Inspect the caller's OS, current Harness and existing local ACS state. Treat
   existing SSH configuration and installation records as discoverable options.
2. Confirm where the Runtime should run before any installation write. If the
   user has not already selected it, ask one question: "Should ACS run on this
   Linux machine, a remote machine reached through SSH, or a WSL distribution?
   For SSH or WSL, which target should I use?" Confirm which client hosts and
   Codex/OpenCode installations should connect to it. An existing SSH alias,
   current project directory or previous installation is not a host choice.
3. Confirm ChatGPT web access after machine and client selection. If the user has
   not already chosen, ask: "Would you like to connect ACS to ChatGPT web now,
   use local Harnesses only, or set up web access later?" Record the explicit
   choice as `enable`, `skip` or `later`. Pass it to Bootstrap with
   `--chatgpt-web`; an existing Tunnel or project is discovery data, not a choice.
4. On the selected host, perform a read-only probe of machine identity, account,
   Linux support and prerequisites. Verify SSH or WSL reachability for the exact
   selected target. Keep the full observed machine identity, login account and
   home directory for apply-time checking before directory or service writes.
5. Use the selected Release's `scripts/acs_bootstrap.py` to preview and apply
   distribution and Runtime installation. Download the standalone Bootstrap
   asset and verify its SHA-256 against that Release's `SHA256SUMS.txt` before
   execution. Supply `--runtime-host local|ssh|wsl`,
   the corresponding `--ssh-target` or `--wsl-distribution`,
   the preview's `--expected-machine-id`, `--expected-account` and
   `--expected-user-home`, and the selected `--harness` values. Pass all three
   expected binding values before apply. The local
   Runtime installer requires `--host-confirmed`; execute it only from the full
   verified Release on that host. A copied setup Skill contains project setup
   tools and the Bootstrap entry; full Runtime dependencies come from the Release.
   SSH and WSL use `--runtime-only` to establish services and owner Authority.
   Local Linux setup configures the selected clients on that host by default;
   `--runtime-only` selects a service-only installation there.
   New v1.3.0 installations enable automatic upgrades by default;
   pass `--no-auto-update` when the user has chosen to opt out or `--auto-update`
   when explicitly enabling them. Regular upgrades preserve an existing
   disabled setting when neither flag is supplied. Inspect the
   actual scheduler readback and connection catch-up status.
6. Configure each selected client on its own host. Install setup and knowledge
   Skills on the selected client hosts. For SSH and WSL, use the returned
   caller-side stdio descriptor with the client's MCP configuration mechanism.
   A Runtime host selected as a client receives the same explicit client setup.
   Keep credentials on the Runtime host and record configuration rollback data.
   For a selected Windows client with a WSL Runtime, configure owner login
   recovery through the Windows/WSL startup procedure below as part of machine
   setup, using the machine/account binding already confirmed by the user.
7. Verify services and actual MCP `tools/list`, `read_profile` and
   `list_projects` from each selected client. An empty project list is a valid
   initial machine installation. `load_project` is required after a project has
   been registered.
8. For `enable`, follow the ChatGPT web setup route below. For `later`, record
   the resume entry and remaining owner actions. For `skip`, record the local
   client scope. Machine setup and web verification have separate readbacks.
9. Report Runtime machine identity and account, client hosts, Release version,
   commit/tree, services, configured Harnesses, observed tools, credential
   references and rollback state, automatic upgrade setting and observed
   scheduling backend/state, plus the web choice, connection state and exact
   pending owner actions. Offer project initialization as the next
   optional lifecycle.

Machine installation selects a service host and a connection path. Runtime
Node enrollment, execution placement and cross-host dispatch require their own
Runtime capability observations.

## Owner Runtime installation contract

Read [the owner Runtime contract](docs/runtime/OWNER-RUNTIME.md) when installing,
using or repairing the selected service. Owner admission follows its trusted
credential, tenant/principal/Authority, active service and objects, explicit
revocation, request deduplication and expected revisions. Roles define duties;
ordinary team members supply slot, principal, role and Harness requirements.
Independent candidate Review, Artifact hashes and deterministic storage remain
acceptance prerequisites.

Keep Connection, Node, Runtime and Endpoint registrations during service or
client recovery. Execution reads actual process and native Session state,
reconnects and prepares the selected user's environment. Native Codex and
OpenCode use that user's tools, MCP servers, plugins, project configuration,
provider, models and approval configuration. Codex reads the selected
approval_policy. Interactive approval/information requests require a native
client handler: the Driver supports server_request_handler, while the standard
headless Receiver factory uses the transport's explicit -32601 response.
Verify the installed API, handler binding and decision/response readback.
API-oriented integrations use the same actual capability and Session readback.

Inspect trusted `SurfaceSettings.remote_endpoints` during machine connection
setup. Its endpoint_id, authority_signing_key_ref, journal_generation,
old_boot_isolation_ref and optional prepare_argv bind the registered target and
saved preparation command. Readiness uses the target's TLS-pinned /healthz;
preparation executes the stored deterministic argument vector and rechecks
health. Keep private keys in their reference store.

Owner commands and Messages have an optional chosen business deadline.
Async returns committed handles; sync waits for the target condition with an
optional caller timeout. Durable Inbox and result tracking follow the actual
Connection/Session and survive caller disconnect. Load current management
documents through machine files. For Review, report the candidate's commit/tree
actually observed through Git, native tools or the selected machine reader,
together with its recorded Evidence.

Existing unspecified service configuration retains shared behavior until
explicit owner migration. Shared deployments retain their configured Grants,
Policy, budgets and bounded reference profiles. Owner adoption preserves
identity, revocation state, project records and the original configuration
backup. Verify the access_mode returned by read_profile after activation.

activate_owner_mode updates the trusted Surface configuration and database
identity/registration records. An existing Receiver has a separately signed
process configuration whose unspecified mode is shared. For owner/native
Receiver migration, preserve its original profile, credential, keys and Node
identity; build the new Runtime/native factory configuration and digest, sign
the next Endpoint registration with the existing Node key, commit the new
revision, then restart and read back the matching mode, digest and Session.
Preserve explicit revocation throughout that transition.

The owner stdio MCP entry automatically maintains committed Message dispatch when
temporal_endpoint is configured. New installation records the selected local
Temporal address/port. A custom configuration with that field omitted retains
pending Outbox state for its separately operated dispatcher. Verify the
configured provider and actual worker/dispatch result.

## Installation verification scope

Use [the installation timing guide](docs/INSTALLATION-PERFORMANCE.md) to keep
machine setup focused. Reuse the current install receipt and completed
readbacks. From each selected client, perform one actual MCP discovery plus
`read_profile` and `list_projects` in the same connection when possible.
Project context checks follow registration and target that project. Read tool
capabilities from the catalog and knowledge Skills; exercise project actions
when the user starts that workflow. `acs_doctor.py` uses machine scope by
default; `--project-id` selects one context and `--deep` is diagnostic scope.

## Startup and transport recovery

Read [startup recovery](docs/runtime/STARTUP-RECOVERY.md) for reboot or disconnect
repair. Reuse the recorded Runtime host/account and client entry. Verify owner
service identity before restoring dependencies; inspect Core, private SSH and
web Tunnel recovery separately. Preserve existing credentials, configured access
mode, durable registrations and signed Runtime facts. Test fault recovery with
isolated ports, then read actual tools/profile through the configured entry.
Machine boot settings require the selected host's administration and a rollback
backup.

### Windows client with a WSL Runtime

During installation or authorized startup maintenance, execute
`scripts/acs_windows_startup.ps1` from the verified Release or its verified
installed setup Skill payload on the selected Windows client, under the
installing Windows account. Verify Windows x64, WSL, Task Scheduler PowerShell
cmdlets and the installed 64-bit .NET Framework C# compiler before apply.
Use the user-confirmed WSL distribution, observed Linux owner account, private installation root and
full machine identity. Pass them as `-WslDistribution`, `-RuntimeUser`,
`-LinuxInstallationRoot` and `-ExpectedMachineId`; obtain these values from
the installation probe and receipt. Use Bootstrap's
`client_connection.background_startup` script source, parameter binding and
sequence when supplied. Run the default preview, execute
`-Apply`, then read back `-Check`. An installation with `startup.enabled=false`
returns `owner_disabled`; report that owner policy. Arrange this procedure as
part of the selected machine setup and carry it through to actual verification.

The task invokes a GUI background host and the stable launcher's
`--maintain-startup` entry. Verify the registered principal, selected action,
single-instance behavior, login trigger and failure retry. For a verified
existing task, retain its task name and use `-AdoptExisting` with the reviewed
`-LegacyEntrypoint`; the helper backs up the task definition and receipt before
migration. During the lock handoff, it identifies the current installation's
Linux maintainer, checks its owner account, reviewed previous entry or stable
same-root command and process creation identity, then sends SIGTERM and waits
for exit before starting the replacement task. A mismatched lock holder requires
owner review. Core, SSH and web processes retain their existing supervision.
Read back task state, Core dependencies, each selected transport and
actual client MCP calls. Record task restart evidence and machine reboot
evidence according to what was measured.

Inspect the actual Docker service/init mechanism before configuring WSL boot.
When startup reports `provider_backend_repair_required`, run the verified
`scripts/acs_docker_backend.py --provider-config <private-provider-config>`
to inspect the daemon's actual data root and preserved ACS store.
A `ready` result completes backend diagnosis. Review a `planned` repair with
the owner; `review_required` needs the listed configuration/workload issues
resolved before a new plan. Obtain explicit authorization for the shared
Docker/containerd changes, and apply only with `--shared-runtime-confirmed`,
the current `--plan-digest`, a new absolute `--backup` directory and the
selected host's OS administration. Verify existing provider containers and
PostgreSQL/Temporal health afterward, then verify SSH, Tunnel and client MCP
readback. Keep installation-specific values in the private receipt.

## Automatic upgrade maintenance

Read [the automatic upgrade guide](docs/AUTOMATIC-UPDATES.md) when managing an
existing installation. Run its installed Bootstrap on the recorded Runtime host
as the same owner. Reuse the stored machine/account/home binding, Harness
selection and web settings. `--set-auto-update on|off|status` controls the policy;
`--update --force-check` checks immediately, and adding `--apply` applies an
eligible update. Report policy, last result, active/previous versions and the
actual backend state: active systemd user timer, registered cron entry or
connection catch-up checks. Host sleep and an inactive user manager affect
scheduled checks.

Automatic activation requires a stable Release in the same major version and
an unchanged license, schema, migration, provider and MCP catalog contract.
A changed contract requires explicit review and a guided upgrade. Verify archive and file
digests, the previous installation, the new locked environment, provider health
and the active identity before activation; shared mode also verifies its
configured Grant authorization. Updates preserve project registrations,
access mode and explicit revocation state. Owner mode adoption is an explicit
configuration/schema transition with backup. Project setup and Compose changes
retain their setup lifecycles. Existing Source records keep their archive identity.

Owned local Skills refresh transactionally; selected remote client Skills are
refreshed through client setup maintenance. Stable launcher commands select the
active version for future MCP and Tunnel connections. Existing sessions keep
their running version. A manual rollback records the rejected version in
`held_version` for explicit review before automatic checks apply that version
again.

Existing installations use the verified
[v1.6.0 Release Bootstrap](https://github.com/D1ChangGeng/Agent-collaboration/releases/tag/v1.6.0)
for a guided Runtime schema and MCP catalog upgrade. Preserve the existing
automatic update policy and verify the known schema migration before activation.
See [the release notes](docs/RELEASE-NOTES-v1.6.0.md).

## ChatGPT web setup route

For a selected web connection, read
[the private Tunnel runbook](docs/runtime/P2-PRIVATE-TUNNEL-PROFILE.md). Fetch its
official documentation links during setup and verify current account/workspace
eligibility before presenting page instructions. The supported personal profile
connects the owner's existing ACS stdio process, trusted credential and
configured access mode. Reference P2 runs retain their recorded Grant binding.

Use the owner's external browser on their client machine for Platform and
ChatGPT account pages. Browser control depends on the current Harness. Verify
actual OS or external browser control on that client, then use the owner's given
setup authorization for opening and navigation within its scope. Seek further
authority only when the intended operation requires it. The owner confirms
required login, permissions, secret entry and connection consent.
Limit embedded browser use to read-only public documentation
retrieval.

When external browser control is unavailable or the owner prefers guided steps,
provide the official link, exact page and current labels, action and expected
result for each step. Await the owner's completion before proceeding with
dependent setup and actual MCP verification. Read-only documentation searches
and fetches can proceed independently of account actions.

Generate the machine-specific plan with `scripts/acs_web_setup.py --choice enable
--runtime-root <verified-release-directory> --config <private-surface-config>
--json`; include `--tunnel-id <id>` once the owner has selected it. Run this on
the confirmed Runtime host, using SSH or WSL when selected. The plan supplies
the exact Runtime command and the install, init, doctor and run sequence. The AI
executes these supported steps and configures service persistence with rollback
data. Treat generated commands as a plan until execution and readback establish
the connection state.

For a managed installation, add `--installation-root <installation-root>` with
the active Release directory and matching private surface config from its state.
The helper verifies those inputs and emits the stable launcher command, so
future Tunnel MCP processes follow activation and rollback. A standalone
verified Release uses its version directory command. Apply the generated MCP
command to the selected existing Tunnel profile when maintaining that connection.

Guide required account login, organization/workspace permissions, runtime-key
provisioning through private storage, and ChatGPT connection consent in the
owner's external browser or the named private storage location. The owner
confirms each required action. Explain its location, purpose and expected
result using the runbook. Keep secret values out of chat, command arguments,
tracked files and reports. After connection, verify discovered tools and actual
`read_profile` and `list_projects` from ChatGPT. An empty project list is valid;
`load_project` and authorized project writes are verified after project setup.

For deferred setup, invoke this Skill again and run the same helper with
`--choice enable`. Report local MCP readiness, Tunnel health and ChatGPT tool
readback individually; unfinished platform or web actions remain explicit
pending steps.

## Project setup lifecycle

For an existing project, inspect the Management Root, its Project/Root identity
and the machine and directory that hold its current files. Use the selected
machine's OS path namespace and verify access through the available machine,
native or Git tools. Inspect the actual repository and commit/tree when the
work depends on a source version. Ask for the smallest missing location or
access fact when observations are incomplete or ambiguous.

Owner registration records durable Project/Root identity, Routes and current
management file locations. A Management Root may be nested in Git or stored in
an authorized standalone directory. `load_project` reads its configured
instruction and knowledge index paths through the selected machine filesystem.
Use `configure_project` with `project_id`, `client_request_id`,
`expected_revision` and `changes` to set or replace `management`,
`instruction_paths` and `knowledge_index_paths`; `management: null` clears the
saved location. A single `load_project` call can select `machine_id` and
`management_path` for that read. Read back the resulting revision,
observed document paths and context completeness.

Agents choose the source version for each WorkItem. Owner `source_baseline`
may be omitted or null; `revise_work` can select, change or clear it when the
WorkItem is eligible for an intent revision. Owner Attempts can report actual
execution source through authenticated receipts after execution. Review and
acceptance use the Agent's inspected commit/tree, exact candidate Evidence and
execution receipts, with independent Reviewer and Finalizer authorization.
Existing Source records are available for explicit historical queries by
`source_id` and `revision`. See [Owner Runtime](docs/runtime/OWNER-RUNTIME.md)
for project registration, current context and acceptance, and
[the adoption contract](docs/runtime/UPGRADE-CONTRACT.md) for schema migration.

For a management workspace, use the explicit command families:

- `workspace bootstrap|adopt|upgrade|repair|validate|uninstall`;
- `route create|adopt|upgrade|list|validate|set-state|rename`.

The Workspace and Route command names are deterministic mechanisms, not a
natural-language
intent parser. Decide the lifecycle from the observed target and user intent
before invoking one. A new Session, Engineer window, machine, or Endpoint does
not by itself justify creating a new Route.

Workspace commands keep the exact supplied management root as their target.
Route adoption registers and minimally annotates a Route while preserving its
existing `AGENTS.md`, `.agents/knowledge/`, references, and state.

The default v0.4.0 directory model is:

```text
Project Git Repository / Source Checkout Root
├── Product code
├── ...
└── Nested Management Root
    ├── AGENTS.md
    ├── .agents/
    └── Route directories
```

Track management documents, knowledge, and Routes in the same project Git
commits as product code. Local and remote copies are separate clones with the
same relative layout; Git synchronization must be performed explicitly. The
manifest records `collaboration_root_mode: nested-repository`; the relative
layout is carried by Git, not by a manifest path field.

Nested setup adds a source-checkout block to Management Root `AGENTS.md` using
`assets/scaffold/workspace/SOURCE_CHECKOUT_BLOCK.md`. It records the source
checkout relative to that management directory and directs all Git synchronization,
pull, staging, and commit operations to the resolved source checkout. The path
is derived from the actual nesting depth and remains portable across clones.
`workspace repair` adds a missing block; an existing conflicting block requires
review before writes proceed.

Keep credentials, private Session data, caches, and temporary logs local; review
their exclusions in the repository-root `.gitignore`. Shared Git ownership
preserves the separate responsibilities and knowledge scopes of Root and Routes.

The only setup write outside the exact management root is its scoped runtime
exclusions in the repository-root `.gitignore`, between
`# ACHP-NESTED:<relative path>:BEGIN` and
`# ACHP-NESTED:<relative path>:END`. Preserve all pre-existing parent blocks and
rules. A nested root has no child `.gitignore`, and its parent does not need
repository scaffolding installed. Legacy manifests without
`collaboration_root_mode` stay unchanged during `adopt`/`repair`; explicit
`workspace upgrade` inside Git migrates a known setup-only child ignore. Custom
child rules require reviewed manual consolidation and cause writes to be refused.

For an existing target, preview first and treat ownership conflicts as a stop
condition. `bootstrap` is for a genuinely new/empty target; `adopt` is for
existing assets; `repair` is limited to a safe managed gap; and `upgrade` is the
explicit boundary for refreshing managed protocol content. See
[references/OPERATING-GUIDE.md](references/OPERATING-GUIDE.md) for the decision
table and [references/UPGRADE-POLICY.md](references/UPGRADE-POLICY.md) for
preservation rules.

The current Workspace schema remains 0.3. This Skill release is v0.4.0 and
hardens lifecycle safety, candidate selection, and Agent-readable operation
guidance without changing the minimal Workspace state model.
Readers remain compatible with schema 0.2 input. New writers use the smallest
stable shape: Root identity and registry location in the manifest, Route
identity in `route.yaml`, and Route lifecycle in the Root registry. Older
derived fields are read for compatibility but are not written again. Validation,
adopt, and repair may continue to read an existing schema 0.2 Workspace or
perform an idempotent no-op; adding a new Route to a schema 0.2 registry first
requires the explicit Workspace upgrade boundary.

`workspace uninstall` currently refuses to change files until a reviewed
ownership plan exists. `route upgrade` is the explicit metadata migration
boundary; it canonicalizes the Route metadata and Root registry while
preserving unrecognized extension fields. `route set-state` and `route rename`
write the Root registry only. Path-moving rename, split/merge, Endpoint
replacement, restore, and rollback are future migration contracts, not
operations implied by the current command list.

Installer ownership hashes and preflight checks are optional setup-integrity
metadata. They do not represent Session progress, checkpoints, or a recovery
cursor. Session/context continuity remains the responsibility of the Harness,
Git/source state, and the durable knowledge system.

Do **not** use this skill merely because a project already uses ACHP.

If the request is to continue an existing Route, replace a Session or
Execution Endpoint, inspect source over SSH, or perform direct cross-session
relay, preserve the existing identity and report the current support boundary.
The setup Skill does not currently provide those runtime operations; do not
invent a replacement Route, persist runtime-only recovery state, or claim an
unverified adapter succeeded.

## Non-goals

Do not use this skill to:
- act as Coordinator, Executor, Reviewer, or another runtime role;
- perform normal task handoff or session relay;
- decide day-to-day Push/Pull actions;
- maintain project knowledge during normal work;
- replace the project's existing architecture/product documentation;
- become a hidden dependency of the collaboration mechanism.

## Setup contract

The installed runtime must satisfy all of these:

1. `AGENTS.md` is the canonical harness-neutral collaboration entry point.
2. The ACHP runtime core is present directly in an explicitly managed block in `AGENTS.md`, with routes to deeper files under `.agents/`.
3. `.agents/knowledge/` is the durable project-level knowledge container.
4. Session relay uses capability-based branching:
   - no cross-session need -> no relay;
   - same-host multi-session -> test only same-host send capability;
   - multi-host -> test cross-host send capability;
   - unknown/unavailable capability -> user manual forwarding;
   - verified capability + addressable destination -> automatic forwarding is allowed.
5. Manual user forwarding is a first-class transport, not an error.
6. Repository synchronization is independent from message transport. Handoffs involving repository changes must state branch, commit, push state, and receiver sync action.
7. Runtime capability observations stay in the current Harness/session context;
   they are not required project files or universal project truth.
8. Harness-specific compatibility is thin:
   - Codex/OpenCode can use `AGENTS.md` directly.
   - Claude Code gets a minimal `CLAUDE.md` import/router to `AGENTS.md`.
9. Existing `AGENTS.md`, `CLAUDE.md`, `.gitignore`, project docs, source, and Git history must be preserved.
10. The setup skill itself is not referenced by runtime instructions.
11. Prefer a `nested-repository` management root with the directory and ignore
    boundaries above. Standalone Workspaces remain supported for compatibility;
    source-state and endpoint claims require evidence.
12. Root registry writes contain stable Route identity, display name, path, and
    lifecycle status only; dynamic/current Route state remains Route-owned.
13. `AGENTS.md` contains only startup-critical, always-on invariants. New
    material is admitted there only after real work demonstrates stable,
    cross-session value that cannot be reliably supplied by retrieved knowledge;
    concrete state and knowledge lifecycle remain in their authoritative
    Route/state/knowledge surfaces.
14. Route creation does not emit an empty Source State record. A Route creates
    `.agents/state/source-state.yaml` only for verified source facts that need
    durable cross-Session value; live Harness/Session/Endpoint observations stay
    in the current execution context.

## Preferred deterministic workflow

Resolve the skill directory as the directory containing this `SKILL.md`.

For repository setup, prefer:

```bash
python3 <skill-dir>/scripts/project_setup.py adopt --root <repo>
```

Use `bootstrap` for a genuinely new repository.

Before applying changes:

```bash
python3 <skill-dir>/scripts/project_setup.py validate --root <repo>
```

A validation failure before first install is expected.

For a preview:

```bash
python3 <skill-dir>/scripts/project_setup.py adopt --root <repo> --dry-run
```

Then apply the setup and validate again.

For a management workspace, use the exact path and inspect before applying:

```bash
python3 <skill-dir>/scripts/project_setup.py workspace adopt --root <workspace> --dry-run
python3 <skill-dir>/scripts/project_setup.py workspace adopt --root <workspace>
python3 <skill-dir>/scripts/project_setup.py workspace validate --root <workspace>
python3 <skill-dir>/scripts/project_setup.py route list --workspace <workspace>
```

When an existing Workspace contains unregistered Route-like directories, list
them without changing the registry, then include only the Route the user has
identified as a long-lived workstream:

```bash
python3 <skill-dir>/scripts/project_setup.py workspace adopt \
  --root <workspace> --list-candidates
python3 <skill-dir>/scripts/project_setup.py workspace adopt \
  --root <workspace> --include-route "C Route" --dry-run
python3 <skill-dir>/scripts/project_setup.py workspace adopt \
  --root <workspace> --include-route "C Route"
```

Do not run the legacy repository `adopt` command against a management workspace.

## Existing-project adoption

Before `adopt`, inspect the repository sufficiently to avoid duplicating or contradicting existing instruction systems.

Preserve existing authoritative documentation. The ACHP scaffold should route to existing product/architecture/roadmap docs when they already exist rather than copying their content into `.agents/knowledge/`.

After installation, fill the applicable `.agents/coordination/PROJECT.md` with
only facts supported by the repository/workspace or explicitly supplied by the
user. Mark unknowns as unknown instead of inventing them. For a workspace,
`.agents/coordination/ROOT-BASELINE.md` is the authoritative Root↔Route contract
and `routes.yaml` is the stable registry.

## Claude Code compatibility

If `CLAUDE.md` does not already import `AGENTS.md`, install only the managed compatibility block that imports `@AGENTS.md`. Do not duplicate the ACHP body into `CLAUDE.md`.

## Completion

When setup is complete:

1. Run validation.
2. Summarize files created/updated and anything intentionally preserved.
3. State whether the repository has uncommitted changes.
4. Recommend committing the setup if appropriate.
5. Explicitly state that normal collaboration now proceeds through `AGENTS.md` and `.agents/`, and that this skill should not be loaded again unless the collaboration setup itself needs maintenance.

For Windows/WSL setup, complete the owner login recovery procedure above and
include its binding, task state, service health and actual MCP readback in the
installation report.
