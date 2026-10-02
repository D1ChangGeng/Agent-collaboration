# Agent Collaboration Operating Guide

This guide is the decision layer for the `agent-collaboration-setup` Skill.
Read it when a user asks to install ACS on a machine or create, adopt, repair,
upgrade, validate, or understand a project setup and the wording does not identify a
safe deterministic command. It is intentionally separate from the scripts:
the Agent interprets intent and reality; the scripts perform bounded file
operations and report observable facts.

The project Workspace lifecycle retains its v0.4 setup profile. Global
installation uses the selected Release's Bootstrap and Runtime installer.
A statement marked
`documented`, `unverified`, `architecture-allowed`, or `unsupported` is not a
promise that the Skill can perform that operation.

## 1. What this Skill is

`agent-collaboration-setup` guides machine installation and project setup.
A machine installation binds ACS services to the chosen Runtime host and owner
account and connects the chosen client Harnesses. A project setup establishes
the repository-native Management Root, identity and Routes. Normal project
work proceeds from `AGENTS.md`, `.agents/`, knowledge Skills and MCP tools.

The Skill can currently provide a bounded, deterministic lifecycle for:

- confirmed local Linux, named SSH target or named WSL Runtime installation;
- release verification and selected client MCP connection setup;
- default automatic upgrades, owner scheduling controls and retained-version
  rollback for installations with the updater;
- repository setup and validation;
- read-only discovery of an exact Source checkout on the caller, a selected SSH
  target or a selected WSL distribution;
- nested management Workspace setup in the same project Git repository;
- standalone Workspace setup for compatibility;
- Route identity and registry operations;
- explicit schema/metadata upgrades;
- selected ownership, marker, path, dry-run, and idempotency checks.

Bootstrap SSH/WSL installation selects a service host and connection transport.
Session brokering, execution Endpoint management, source synchronization and
message delivery belong to their Runtime mechanisms and capability checks.

### Machine installation lifecycle

Global installation is complete when the selected host's services and the
selected clients' MCP connections are verified. A project list with zero
entries is a valid starting state. Project paths, collaboration goals and
Management Roots are supplied when the user begins project setup.

For an existing installation's automatic upgrade maintenance, use the recorded
binding and controls below. Use this order for a new global install or a guided
setup operation that requires a placement plan:

1. Inspect the caller host's OS, active Harness and existing ACS installation.
2. Resolve the user's Runtime placement choice: this Linux host, a named remote
   SSH target, or a named WSL distribution. If it was not supplied, ask one
   placement question. Resolve the client host(s) and Codex/OpenCode selection
   from the user's intended use and current Harness; ask only when ambiguous.
   Resolve whether the installer owner wants a ChatGPT web connection now:
   `enable`, `skip` or `later`. Ask once when this preference is unknown and
   record `skip` or `later` explicitly. This web choice and the machine/client
   selection are required before apply; a project list remains optional.
3. Probe the selected host read-only. Observe its machine identity, login
   account, home directory, Linux support and required tools. Verify that exact
   SSH target or WSL distribution before planning writes. Pin the full machine
   identity, account and home directory before directory or service mutations.
   Existing aliases and project paths are options to inspect, not evidence of
   a chosen installation destination.
4. Preview the selected Release's Bootstrap with `--runtime-host`, its matching
   `--ssh-target` or `--wsl-distribution`, `--harness` and `--chatgpt-web`.
   Bind apply to the
   preview's full identity using `--expected-machine-id`, `--expected-account`
   and `--expected-user-home`; supply all three before apply.
5. Apply the verified Release on that Runtime host. The bounded local installer
   receives `--host-confirmed` from the machine installation flow. Run Runtime
   setup from the full verified Release; installed Skill copies provide the
   decision guide, Bootstrap entry and project scaffold tools. SSH/WSL use
   `--runtime-only` for services and owner Authority. Local Linux defaults to
   selected client setup on the same host and also supports `--runtime-only`.
   New v1.3.0 installations enable automatic upgrades by default. Pass
   `--no-auto-update` when the user has opted out or `--auto-update` to enable
   explicitly. Regular upgrades preserve an existing disabled setting when
   neither flag is supplied. Inspect scheduler readback.
6. Install setup and knowledge Skills and configure MCP on each selected client
   host. SSH/WSL return a caller-side stdio descriptor for the remote MCP process;
   use each client's configuration mechanism and preserve rollback copies.
   Select the Runtime host explicitly as a client if it should receive client
   configuration and Skills.
7. Read back services, `tools/list`, `read_profile` and `list_projects` from
   each selected client. Report observed readiness and any remaining checks.
8. When `enable` is chosen, inspect the install receipt's `web_setup` and run
   `scripts/acs_web_setup.py --choice enable --runtime-root <verified-release>
   --config <owner-private-config> [--tunnel-id <owner-tunnel>]` from the full
   Release or installed setup Skill. Follow the generated steps and current
   official indexes in [ChatGPT Web Setup](../docs/runtime/P2-PRIVATE-TUNNEL-PROFILE.md).
   The AI prepares the native Tunnel client and configuration, invokes its
   discovery/initialization, doctor and run tools when available, and verifies
   owner Grant and local MCP on the confirmed Runtime host. Use the owner's
   external browser on their client host for Platform and ChatGPT account steps.
   Browser navigation requires working OS or external browser control verified
   in the current Harness. Use the owner's given setup authorization for
   navigation within its scope; seek further authority only when required.
   The owner
   confirms required login, permissions, secret entry and connection consent.
   Fetch official documentation read-only independently of account actions.
   For guided steps, provide official links, exact pages, current labels, actions
   and expected results; await completion before dependent setup and actual web
   MCP verification. Keep the key in
   private configuration and refer to it by name, rather than embedding its
   bytes in reports or command arguments.
   For a managed installation, add `--installation-root <installation-root>`
   with the active Release directory and matching private config from its state.
   The verified binding produces the stable launcher command for the selected
   Tunnel profile. A standalone verified Release uses its version directory
   command. Update the selected existing profile when maintaining its connection.
   Limit embedded browser use to read-only public documentation retrieval.
9. Complete actual ChatGPT tool calls against an authorized real project:
   profile/project reads, scoped collaboration writes, refused operations,
   reconnect and revocation read-back. Generated instructions establish
   `awaiting_owner_actions`, not an operational web connection. The final
   installation report explains those pending actions and their exact screens
   and official guidance; `skip` and `later` retain a clearly stated web choice
   and a direct later setup entry.

The machine installation report records the selected transport and target,
observed machine identity and account, owner credentials by reference, Release
version and source binding, services, client host/Harness connections and
rollback data. Include automatic upgrade policy, observed scheduling
backend/state, connection catch-up, last result and next eligible check.
Include ChatGPT web choice, verified web state and any owner
actions with concrete instructions. Machine installation binding and Runtime Node identity are
separate records; dispatch claims require a live Node/Driver verification.

### Automatic upgrade maintenance

Read [Automatic upgrades](../docs/AUTOMATIC-UPDATES.md) and inspect the existing
installation on its recorded Runtime host. Run the installed Bootstrap as the
same owner, reusing its machine/account/home binding, Harness selection and web
settings. Use `--set-auto-update on|off|status` for policy controls and
`--update --force-check` for an immediate check; add `--apply` to activate an
eligible candidate.

The updater checks stable Releases daily and makes failed checks eligible for
retry after an hour. Prefer an owner systemd user timer, use cron when available,
and retain background catch-up on new stable-launcher MCP connections. Report
an observed active timer, a registered cron entry or connection checks; host
sleep, cron daemon state and user manager availability determine execution.

Automatic candidates keep the same major version and license, schema, migration,
provider and MCP catalog contracts. A changed contract requires explicit review
and a guided upgrade. Archive digests, installed-file ownership, a new locked
environment, provider health and existing Grant authorization are checked
before activation. The update uses existing projects, SourceBindings, Grants
and Compose services; creating or changing them follows their setup lifecycle.

Owned local Skills refresh transactionally. Refresh Skills on separate client
hosts through client setup maintenance. Stable local, SSH, WSL and Tunnel launch
commands select the active version for a future MCP process; running sessions
retain their version. `--rollback --apply` verifies and reactivates the previous
Release and holds the rejected version in `held_version` for explicit review.
Existing v1.2.0 installations need one AI-guided upgrade with the verified
v1.3.1 Release Bootstrap before these controls are available.

### Workspace placement

Default to a management root inside the same project Git repository as product
code. Standalone Workspaces remain supported for compatibility.

```text
Project Git Repository / Source Checkout Root
├── Product code
├── ...
└── Nested Management Root
    ├── AGENTS.md
    ├── .agents/
    └── Route directories
```

Track management documents, knowledge, and Routes in project Git commits with
product code. Local and remote clones retain the same relative layout, but Git
synchronization requires explicit operations. The manifest records
`collaboration_root_mode`, while Git carries the layout.

Keep the supplied nested root as the CLI target. The only parent write is its
scoped runtime exclusions in repository-root `.gitignore`, between
`# ACHP-NESTED:<relative path>:BEGIN` and
`# ACHP-NESTED:<relative path>:END`. Preserve all pre-existing parent rules and
blocks; parent repository scaffolding is not required. Nested roots have no
child `.gitignore`. For legacy manifests missing the mode, `adopt`/`repair`
preserve the manifest; explicit `workspace upgrade` inside Git migrates only a
known setup-only child ignore. Custom child rules require reviewed manual
consolidation and cause writes to be refused.

### Existing-project Source discovery

Before creating or adopting a Management Root or registering a SourceBinding,
identify the checkout that the project actually uses. Runtime service placement,
client placement, Source checkout location and Git hosting are separate facts.
The service host may hold no project checkout; a GitHub URL identifies a hosting
repository and supplies no filesystem access to an existing local or SSH clone.

1. Inspect the current project Session's working directory and explicit project
   paths. Read its existing Root/Route identity and repository context. Reuse
   confirmed host bindings and exact source paths from the caller's project
   context as read-only discovery candidates. A past report is a hint to probe.
2. Probe the actual current-session checkout first. If its path is absent or the
   Source location is unclear, inspect only the specific local path and selected
   SSH/WSL host and path already authorized by this Session or the user. Do not
   enumerate SSH hosts, recursively search home directories or assume a project
   is on the Runtime service host.
3. Run `python scripts/acs_source_discovery.py --path <checkout-or-management-root> --include-untracked`.
   For remote Source add `--ssh-target <authorized-alias>` or
   `--wsl-distribution <selected-distribution>` and supply an absolute path in
   that machine's filesystem namespace. For a known nested Root supply
   `--management-path <root-on-that-same-host>`. Remote paths are JSON stdin
   data; the caller never resolves them as caller-side filesystem paths.
4. Compare `source_machine_binding` (machine, account and home),
   `repository_root`, Root/Project identity, credential-free repository remotes,
   commit, tree, branch and working-tree state against the requested project.
   Use `--expected-project-id`, `--expected-root-id`, `--expected-commit` and
   `--expected-repository` when those facts are authoritative; an identity or
   baseline mismatch produces `conflict`. Use the `--expected-machine-id`,
   `--expected-account` and `--expected-user-home` checks for a previously
   confirmed Source machine. Dirty state is reported; discovery preserves edits.
5. Prefer an observed exact match to the live project Session's repository and
   machine binding. Multiple matching clones, unknown location or conflicting
   identity require the smallest Source host/path choice. Do not select a
   different clone, create a clone or relocate Source as a discovery fallback.
6. Explain the observed topology before planning setup or registration: Runtime
   host, Source checkout host/account/path, Management Root, Git hosting and
   how authorized Runtime Source access will work. `observed_candidate` is
   discovery evidence. Registration requires its own exact Source scope,
   credentials, preview and read-back. A configured SSH client connection does
   not by itself establish Runtime Source provider access.

The observation reads an exact path and its ancestor metadata, and optionally
one explicitly named nested Management Root. It creates no project files,
Grants or SourceBindings and does not synchronize Git. `need_location` means
the requested checkout has not been found; `unavailable` reports a failed or
unsafe probe. In either case retain existing project identity and collect only
the location or access information required to continue.

## 2. Core mental model

Keep these objects distinct. Do not create a new durable object merely because
a Session, process, machine, or chat window changed.

| Object | Durable meaning | What it is not | Current Skill boundary |
|---|---|---|---|
| **Root / Project Collaboration Workspace** | One long-lived management identity and control surface for a collaboration world | A source checkout, running process, or per-turn log | Workspace setup/registry is implemented narrowly |
| **Route** | One long-lived workstream, goal, or development line under a Root | A chat window, Engineer, machine, or Endpoint | create/adopt/list/validate/set-state/rename/upgrade are implemented narrowly |
| **Session** | A temporary Harness conversation/execution context | A Route identity or durable project state | Harness-owned; no Skill-level attach API |
| **Engineer** | A role/person participating in a Route | A specific Session or machine | Protocol concept; no identity service |
| **Execution Endpoint** | Where Route work is executed | The Route itself or a Git remote | Replacement/rebinding is a future contract, not a current command |
| **Source relationship** | Whether and how a Route relates to source assets | Message transport | Checkout discovery yields candidates; Runtime SourceBinding admission is a separate workflow |
| **Source access** | How source can be read or changed (local, shared, SSH, evidence-only, unavailable) | Source history or ownership | Exact local/selected SSH/WSL checkout observation is read-only; provider read/write scope must be verified separately |
| **Source synchronization** | How source changes move between locations (Git, shared checkout, transfer, manual) | Session messaging | Git policy is documented; synchronization is external to this Skill |
| **Source State Evidence** | Verified source facts worth preserving across Sessions | Live liveness, freshness, or Session progress | Optional Route-owned file; created only when justified |
| **Message Transport** | How collaboration messages travel (manual relay or verified automatic path) | Git synchronization | Manual relay is the portable protocol baseline; direct relay is unverified |

### Durable state rule

Persist only stable identity, ownership, lifecycle, and high-value verified
facts that future Sessions cannot cheaply recover from authoritative sources.
Keep current Session progress, live capability observations, process liveness,
temporary Endpoint availability, and conversation details in the current
Harness context. Do not add checkpoints or recovery metadata to make this Skill
look like a workflow engine.

## 3. Support vocabulary

Use these labels in reasoning and reports. Never collapse them into a generic
“supported” claim.

| Label | Meaning |
|---|---|
| **supported (narrow)** | The current Skill has instructions, deterministic mechanism, invariant validation, and representative local evidence for a bounded input shape. |
| **supported (protocol)** | The protocol defines a safe interaction pattern, but a provider-specific runtime adapter is not implied. Manual user relay is in this category. |
| **partial** | Some layers work, but at least one decision, validation, safety, or user-journey link remains incomplete. |
| **documented / unverified** | The repository explains a relationship or policy, but the actual environment or E2E behavior has not been verified. |
| **architecture-allowed** | The design can represent the concept; the current Skill has no complete operation for it. |
| **unsupported** | The current Skill has no honest mechanism or evidence for the requested capability. |
| **unknown / not-measured** | The fact is not available from the current context. Do not infer it from a Harness brand, path name, or historical record. |

The detailed status and evidence ledger is in
[CAPABILITY-MATRIX.md](CAPABILITY-MATRIX.md). The regression inventory is in
[SCENARIO-MATRIX.md](SCENARIO-MATRIX.md).

## 4. Project setup invocation: observe before asking

When a user gives a natural-language request, do not ask for internal schema
fields or immediately choose a command. Use this order:

1. **Resolve the scope.** Global installation follows the machine lifecycle
   above. For project requests, determine whether the target is a Workspace,
   a Route, or ordinary project work. If it is
   ordinary work after setup, stop using this Skill and follow `AGENTS.md`.
2. **Inspect the supplied context.** Read the current working directory,
   explicit target path, Git status when repository mode is relevant, and the
   smallest relevant existing `AGENTS.md`, `CLAUDE.md`, `.agents/manifest.json`,
   registry, Route metadata, and ownership markers. Existing-project requests
   follow the Source discovery flow above before selecting a setup path or
   SourceBinding; inspect the actual local or selected SSH/WSL checkout.
3. **Classify the observed state.** Use the Root and Route tables below. A
   missing optional Source State file is not an error.
4. **Infer only safe facts.** Reuse explicit user statements and authoritative
   files. Do not infer a source baseline, Endpoint, transport capability, or
   project identity from a Harness name, historical path, or filename alone.
5. **Ask only behavior-changing unknowns.** A question is justified only when
   the fact cannot be discovered, cannot be safely inferred, changes the next
   operation, and is needed at the current lifecycle point.
6. **Preview.** Run the narrowest relevant command with `--dry-run` when it
   mutates a target. Review conflicts and ownership before applying.
7. **Apply deterministically.** Use the exact supplied Workspace path; do not
   use the repository command family against a management Workspace.
8. **Read back and validate.** Validate the resulting invariant, not merely the
   process exit code. Preserve the distinction between applied, refused,
   conflicted, and unverified outcomes.
9. **Report the stable state.** State the target path, operation, files changed
   or preserved, validation result, and any capability that remains unknown or
   unsupported.

### Facts to discover automatically

- current working directory and an explicitly supplied target path;
- whether the target exists, is a directory, is empty, or is a file;
- existing `AGENTS.md`, `CLAUDE.md`, `.agents/`, manifest, registry, markers,
  Route metadata, knowledge, references, and Source State;
- whether the target is a Git repository, its root, branch, HEAD, and dirty
  state when repository synchronization is actually in scope;
- Source checkout host/account/path, tree and credential-free hosting locators
  from exact read-only probes when existing-project setup or binding is in scope;
- existing Route IDs/paths and duplicate or collision conditions;
- ownership evidence and managed-file drift that the validator can observe.

### Facts that may be safely inferred

| User expression or observed fact | Safe interpretation |
|---|---|
| “为这个项目建立协作空间” | A Root creation request, after resolving the target path |
| “这个目录已经有资料，接入协作系统” | Existing assets; inspect and use safe adopt, not bootstrap |
| “把之前那条路线接进来” | Existing long-lived Route; inspect and adopt only if it is not registered |
| “继续原来的路线” | Preserve Route identity; this is Session attach/continuation semantics, not Route creation. Current Skill has no attach command. |
| “原来的工程师窗口没了，重新开一个” | Session replacement; do not create a new Route. Current Skill cannot broker the replacement. |
| “工程师换到另一台电脑” | Endpoint/machine change; revalidation is required in principle, but no current Endpoint replacement operation exists. |
| “消息由我来转发” | User-mediated relay is the selected message transport. |
| “没有 GitHub，但可以 SSH” | Observe the exact authorized SSH Source path; independently verify Source provider scope, synchronization and baseline. |
| “代码以后才开始” | Root/Route structure may be ready while source relationship remains pending or unbound. |

### Questions that are usually justified

- “协作空间应放在哪个目录？” when no unambiguous target path exists.
- “这个目录里的现有内容是否都属于要接入的项目？” before adopting a
  non-empty directory with mixed ownership.
- “你要建立新的长期路线，还是继续哪一条已有路线？” when multiple
  Routes match and the user's wording is ambiguous.
- “当前要维护的是源码仓库，还是管理 Workspace？” when the path could
  safely be interpreted as either mode.
- “项目实际使用的是哪台机器上的哪个源码目录？” only after scoped
  current-session and authorized local/SSH/WSL path probes leave Source location
  unknown or multiple clones ambiguous.

### Questions to avoid

Do not ask for internal fields or facts that are already discoverable or do not
change the current operation: schema keys, optional Source State fields,
future Sessions, a preferred Git provider, a nonexistent Endpoint, or a
transport capability that the current Harness has not actually exposed.

## 5. Root state classification and operation choice

Classify the target before selecting a command:

| Observed Root state | Decision | Current operation |
|---|---|---|
| Target path is absent | Confirm the intended path and whether a new management object is wanted | `workspace bootstrap` for a Workspace; repository `bootstrap` only for a genuinely new repository |
| Existing empty directory | Confirm it is the intended collaboration object | Workspace bootstrap or repository bootstrap, according to mode |
| Existing non-collaboration assets | Preserve assets and add bounded managed setup | `workspace adopt` or repository `adopt`; preview first |
| Current valid Root | Do not set it up again; interpret the user's actual next goal | `validate`, Route operation, or an honest unsupported/unverified response |
| Legacy schema 0.2 Root | Preserve readable state and make migration explicit | `workspace upgrade` / relevant `route upgrade` |
| Partial or conflicting Root | Inspect the exact gap and ownership before writing | `repair` only for a safe managed gap; otherwise stop and ask or require explicit upgrade |
| Path is a file, traversal escapes, malformed marker, or duplicate identity | Fail closed | No mutation; report the concrete refusal |
| Unrelated directory merely containing `AGENTS.md` or `.agents/` | Treat as a candidate, not proof of Route identity | Inspect/confirm before registration; never silently claim it is a Route |

### Root operation boundaries

- `bootstrap` establishes a new object only when the mode and target state make
  that safe.
- `adopt` adds bounded setup to existing assets and preserves project-owned
  content.
- `repair` restores a missing, clearly managed setup component; it is not a
  permission to overwrite arbitrary project edits.
- `upgrade` is the explicit schema/metadata migration boundary.
- `validate` reads and reports invariants; it should not be used as evidence of
  Session attach, Endpoint health, or source freshness.
- `uninstall` is guarded for Workspaces and destructive modes require explicit
  authorization and ownership evidence.

### Exact-path and validation boundary

All Workspace and Route command entry points use the exact supplied Workspace
path and reject a path that traverses a symlink, junction, or other reparse
point. `workspace validate`, `route ...`, and `--list-candidates` apply the same
guard as Workspace setup writes; none of these commands silently follows an
alias to a different management Root.

## 6. Route state classification and operation choice

| Observed Route state | Decision | Current operation or response |
|---|---|---|
| New long-lived workstream | Create a new durable identity | `route create` |
| Existing long-lived Route not registered | Adopt in that Route's own migration window | `route adopt` |
| Registered Route and user wants to continue | Keep identity and read Route instructions/knowledge | Attach is a semantic requirement; no current Skill attach command |
| Legacy Route metadata | Canonicalize metadata only | `route upgrade` |
| Registered Route health check | Read current files and registry | `route validate` / `workspace validate` |
| Missing managed Route component | Distinguish Root-owned and Route-owned gaps | Root `workspace repair` restores Root-owned files. There is no standalone `route repair`; `route adopt` previews and creates only missing canonical Route scaffold files while preserving existing Route-owned content. |
| Endpoint, machine, or Session changed | Preserve Route identity and re-evaluate runtime/source facts | No current Endpoint or Session replacement mechanism; label unverified/unsupported |
| Collaboration behavior or topology changes | Treat as explicit migration, not metadata upgrade | No current collaboration migration command |

Never create a Route merely because:

- a new Harness window was opened;
- an Engineer Session was replaced;
- a machine or Endpoint changed;
- a user asked to “continue”; or
- a source checkout moved.

## 7. Deterministic command map

Use the command family that matches the object. These commands do not decide
the user's semantic intent for you.

| Intent after observation | Command family | Required boundary |
|---|---|---|
| Add ACHP to an existing repository | `project_setup.py adopt --root <repo>` | Preserve project files; preview and validate |
| Initialize a genuinely new repository | `project_setup.py bootstrap --root <repo>` | Confirm target semantics and empty/new state |
| Change managed repository templates | `project_setup.py upgrade --root <repo>` | Explicit migration; preserve project-owned knowledge |
| Restore a missing managed repository file | `project_setup.py repair --root <repo>` | Verify ownership and avoid replacing intentional edits |
| Check a repository | `project_setup.py validate --root <repo>` | Report validator scope; do not claim runtime support |
| Adopt or initialize a management Workspace | `project_setup.py workspace <mode> --root <workspace>` | Use the exact supplied management root; nested mode may update only its scoped block in the repository-root `.gitignore` outside that root |
| Create a new Route | `project_setup.py route create --workspace <workspace> ...` | The path must be absent unless the same complete Route is already registered as an idempotent no-op; use `route adopt` for existing work |
| Adopt an existing Route | `project_setup.py route adopt --workspace <workspace> --path <route> [--route-id <id>]` | Preserve Route-owned files and state; a valid existing `route.yaml` supplies its durable custom `route_id` when the CLI ID is omitted |
| Canonicalize Route metadata | `project_setup.py route upgrade ...` | Metadata migration only |
| List/health-check Routes | `route list` / `route validate` | Registry/file facts only |
| Continue an existing Route in a new Session | No current command | Read existing context, preserve identity, and state that attach is not provided by this Skill |
| Replace an Endpoint or machine | No current command | Do not synthesize durable Endpoint state; require an independently verified procedure |
| Discover an existing Source checkout | `acs_source_discovery.py --path <exact-path> [--ssh-target <selected-host> / --wsl-distribution <selected-distro>]` | Read-only candidate evidence; verify the actual host and Project/Root/repository identity before SourceBinding |
| Use direct relay | No current Skill command | Verify the exact transport independently |

## 8. Source and message topology

Keep these dimensions orthogonal:

1. **Management/execution placement:** where the Workspace and actual work
   happen.
2. **Filesystem relationship:** shared directory, separate clone, remote path,
   or evidence-only view.
3. **Source relationship:** bound, pending, unbound, or unavailable.
4. **Source access:** local read/write, shared checkout, SSH, evidence-only, or
   unavailable.
5. **Source synchronization:** Git, shared filesystem, transfer, or manual
   procedure.
6. **Source evidence:** which verified facts justify a durable baseline.
7. **Message transport:** manual relay or an exact, verified automatic path.

GitHub is not a setup prerequisite. A Git remote is not proof of current
source access, and SSH access is not proof of Git synchronization. A successful
message send attempt is not proof of delivery or execution. Unknown capability
stays unknown until observed in the current Harness context.

### Current truthful boundary

- Manual user relay: supported at the protocol/policy level.
- Git synchronization: documented contract; execution depends on the user's
  repository and Harness environment.
- Source discovery: exact local/selected SSH/WSL path observations report
  candidate checkout identity. Local temporary-repository invariants are tested;
  live transport requires environment-specific verification. Source
  provider authorization and read/write capability are checked separately.
- Direct relay, Session enumeration/targeting, and cross-Harness runtime
  collaboration: unverified or unsupported by this setup Skill.
- Optional Route Source State: use only for verified source facts with durable
  cross-Session value. Never fill it with live Session, Endpoint, liveness, or
  freshness observations.

## 9. Validation and final reporting

Validation must prove the target invariant and must be scoped to what the
validator actually checks. For a setup operation, read back:

- exact target path and object identity;
- required managed files and markers;
- manifest/registry/Route metadata coherence;
- ownership preservation and conflicts;
- schema/version compatibility;
- dry-run non-mutation when previewing;
- repeated-operation convergence when idempotency is claimed.

For a Route, also check the required scaffold and the Root registration. The
absence of optional Source State is valid when no durable source fact has been
verified.

Do not turn a green setup validator into claims about:

- Session attach or replacement;
- Endpoint reachability or machine health;
- source freshness, branch synchronization, or push completion;
- SSH access;
- direct message delivery;
- another Harness's runtime behavior.

Use a completion report shaped like:

```text
Object: <repository | Workspace | Route>
Path: <exact path>
Intent interpreted as: <create | adopt | upgrade | repair | validate | unsupported>
Operation: <command or no command>
Changed: <files or none>
Preserved: <project-owned files/state>
Validation: <checks and result>
Runtime/source/transport facts: <verified facts only; otherwise unknown/unverified>
Next action: <stable next step or explicit user decision>
```

If a requested journey lacks a mechanism, say so plainly and preserve the
long-lived identity. Do not invent a new Route, write a runtime checkpoint, or
imply that a design document supplied the missing evidence.

## 10. Representative playbooks

### New management Workspace

1. Resolve the exact Workspace path.
2. Inspect whether it is absent, empty, or contains unrelated assets.
3. Preview `workspace bootstrap` or `workspace adopt` as appropriate.
4. Apply only after conflicts and ownership are clear.
5. Run `workspace validate` and read back the Root manifest/registry.
6. Create a Route only when the user has a distinct long-lived workstream.

### Existing management Workspace

1. Read the Root profile and registry before asking which Route to use.
2. If the user names an existing Route, preserve its identity and inspect it.
3. If the Route is unregistered but clearly long-lived, use its own adopt phase.
4. If the Route is already registered, do not run create; the current Skill has
   no attach command, so report the semantic gap and continue from existing
   `AGENTS.md`/knowledge when the Harness can do so.

For an unregistered or registered partial Route, `route adopt --dry-run` lists
the missing canonical scaffold files without writing them. Applying the same
operation creates only those missing files, preserves existing `AGENTS.md`,
knowledge, references, Source State, and other Route-owned content, and then
validates the completed Route. Root `workspace repair` remains scoped to Root
setup and does not silently take ownership of Route-owned gaps.

### Existing repository

1. Inspect existing instruction files and project ownership.
2. Use repository `adopt`, not `bootstrap`, for a populated project.
3. Preview, apply, validate, and review the diff.
4. Preserve project-owned knowledge, tasks, handoffs, source, and history.

### User asks to “continue” after a new window or machine

1. Map the request to the existing Route, not a new Route.
2. Read the existing Route identity and authoritative knowledge.
3. Keep Session/Endpoint facts in current context.
4. State that this Skill does not implement Session attach or Endpoint
   replacement. Do not fabricate a successful rebind.

### User mentions SSH or a remote Engineer

1. Resolve whether the next action requires source inspection, artifact
   retrieval or message relay from the request and project context.
2. Distinguish SSH source access from Git synchronization and message transport.
3. For Source inspection, probe the exact authorized host and path with
   `acs_source_discovery.py`. Ask for host/path only if context and scoped probes
   cannot establish a unique intended checkout.
4. Read back machine and checkout identity, keep discovery candidates separate
   from registered Source access, and verify provider authorization before binding.

## 11. When no current operation exists

Use this response shape internally and in the user-facing report:

```text
The request maps to <semantic lifecycle>, and the existing <Root/Route>
identity should be preserved. The current setup Skill has no deterministic
operation for that lifecycle. I will not create a replacement identity or
persist runtime-only state. The available next step is <read/validate/manual
relay/external verified procedure>, with the missing capability left
unverified until evidence exists.
```

This is an honest completion boundary, not a request to expand the Skill into
a runtime orchestration platform.
