---
name: agent-collaboration-setup
description: Install, bootstrap, adopt, repair, upgrade, validate, or safely manage removal of the ACHP harness-agnostic collaboration scaffold in a source repository or Project Collaboration Workspace. Workspace removal is guarded until ownership is reviewed. Use only when the user explicitly asks to set up or change the collaboration mechanism itself. Do not use for normal project planning, coding, reviews, handoffs, Git synchronization, or knowledge maintenance after setup.
license: MIT
metadata:
  version: "0.4.0"
  scope: "setup-only"
  protocol: "ACHP"
---

# Agent Collaboration Setup

This skill is an **installer/configurator**, not the collaboration runtime. It can
initialize either a repository-oriented project or a non-Git Project
Collaboration Workspace that manages long-lived Routes and points to separate
Execution Endpoints and Source Repositories.

Its job is to install or maintain the ACHP project scaffold so future sessions can collaborate from repository-native instructions and state. After setup, ordinary collaboration MUST run from the project's `AGENTS.md` and `.agents/` files without loading this skill again.

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

- `bootstrap`: initialize ACHP in a new/blank repository.
- `adopt`: add ACHP to an existing repository without replacing existing project guidance.
- `upgrade`: update ACHP-managed protocol/template files while preserving project-owned state.
- `repair`: restore missing ACHP-managed setup files.
- `validate`: verify the ACHP installation and routing.
- `uninstall`: remove ACHP-managed repository setup while preserving project
  knowledge by default. The Workspace form is currently guarded; see the
  Workspace schema boundary below.

For a management workspace, use the explicit command families:

- `workspace bootstrap|adopt|upgrade|repair|validate|uninstall`;
- `route create|adopt|upgrade|list|validate|set-state|rename`.

These command names are deterministic mechanisms, not a natural-language
intent parser. Decide the lifecycle from the observed target and user intent
before invoking one. A new Session, Engineer window, machine, or Endpoint does
not by itself justify creating a new Route.

Workspace commands use the exact supplied path and never climb to a Git root.
Route adoption registers and minimally annotates a Route while preserving its
existing `AGENTS.md`, `.agents/knowledge/`, references, and state.

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
11. A Project Collaboration Workspace may be non-Git; source-state and endpoint
    claims remain explicit `unknown`/`unverified` until evidence is bound.
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
