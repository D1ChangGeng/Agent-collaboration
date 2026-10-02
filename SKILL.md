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
installation and a project's Management Root. Global installation establishes
the selected Runtime host and client connections. Project setup can follow
later when the user invokes this Skill for a project. The preferred Management
Root is nested in the project's Git repository; standalone Workspaces remain
supported for compatibility.

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
   distribution and Runtime installation. Supply `--runtime-host local|ssh|wsl`,
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
6. Configure each selected client on its own host. Install setup and knowledge
   Skills on the selected client hosts. For SSH and WSL, use the returned
   caller-side stdio descriptor with the client's MCP configuration mechanism.
   A Runtime host selected as a client receives the same explicit client setup.
   Keep credentials on the Runtime host and record configuration rollback data.
7. Verify services and actual MCP `tools/list`, `read_profile` and
   `list_projects` from each selected client. An empty project list is a valid
   initial machine installation. `load_project` is required after a project has
   been registered.
8. For `enable`, follow the ChatGPT web setup route below. For `later`, record
   the resume entry and remaining owner actions. For `skip`, record the local
   client scope. Machine setup and web verification have separate readbacks.
9. Report Runtime machine identity and account, client hosts, Release version,
   commit/tree, services, configured Harnesses, observed tools, credential
   references and rollback state, plus the web choice, connection state and exact
   pending owner actions. Offer project initialization as the next
   optional lifecycle.

Machine installation selects a service host and a connection path. Runtime
Node enrollment, execution placement and cross-host dispatch require their own
Runtime capability observations.

## ChatGPT web setup route

For a selected web connection, read
[the private Tunnel runbook](docs/runtime/P2-PRIVATE-TUNNEL-PROFILE.md). Fetch its
official documentation links during setup and verify current account/workspace
eligibility before presenting page instructions. The supported personal profile
connects the owner's existing ACS stdio process and Grant.

Generate the machine-specific plan with `scripts/acs_web_setup.py --choice enable
--runtime-root <verified-release-directory> --config <private-surface-config>
--json`; include `--tunnel-id <id>` once the owner has selected it. Run this on
the confirmed Runtime host, using SSH or WSL when selected. The plan supplies
the exact Runtime command and the install, init, doctor and run sequence. The AI
executes these supported steps and configures service persistence with rollback
data. Treat generated commands as a plan until execution and readback establish
the connection state.

Ask the owner to perform only required account login, organization/workspace
permissions, runtime-key provisioning through private storage, and ChatGPT
connection confirmation. Explain each action's location, purpose and expected
result using the runbook. Keep secret values out of chat, command arguments,
tracked files and reports. After connection, verify discovered tools and actual
`read_profile` and `list_projects` from ChatGPT. An empty project list is valid;
`load_project` and authorized project writes are verified after project setup.

For deferred setup, invoke this Skill again and run the same helper with
`--choice enable`. Report local MCP readiness, Tunnel health and ChatGPT tool
readback individually; unfinished platform or web actions remain explicit
pending steps.

## Project setup lifecycle

For an existing project, discover its working Source before choosing a setup
or SourceBinding target. Inspect the session checkout, Management Root identity
and authorized existing SourceBinding metadata, then probe related local or
authorized SSH/WSL paths with `scripts/acs_source_discovery.py --include-untracked`.
Compare actual machine/account, repository root and commit/tree. Ask for the
smallest missing location or access fact when observations are incomplete or
ambiguous. Use the discovered host's own path namespace; see
[Source discovery](docs/runtime/SOURCE-DISCOVERY.md) and
[project adoption](docs/runtime/PROJECT-ADOPTION.md).

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
