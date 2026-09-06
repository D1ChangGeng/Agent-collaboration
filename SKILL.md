---
name: agent-collaboration-setup
description: Install, bootstrap, adopt, repair, upgrade, validate, or safely manage removal of the ACHP harness-agnostic collaboration scaffold in a source repository or Project Collaboration Workspace. Workspace removal is guarded until ownership is reviewed. Use only when the user explicitly asks to set up or change the collaboration mechanism itself. Do not use for normal project planning, coding, reviews, handoffs, Git synchronization, or knowledge maintenance after setup.
license: MIT
compatibility: Agent Skills compatible harness with filesystem read/write access; Git is optional for management workspaces; Python 3.9+ is recommended for deterministic setup scripts.
metadata:
  version: "0.2.0"
  scope: "setup-only"
  protocol: "ACHP"
---

# Agent Collaboration Setup

This skill is an **installer/configurator**, not the collaboration runtime. It can
initialize either a repository-oriented project or a non-Git Project
Collaboration Workspace that manages long-lived Routes and points to separate
Execution Endpoints and Source Repositories.

Its job is to install or maintain the ACHP project scaffold so future sessions can collaborate from repository-native instructions and state. After setup, ordinary collaboration MUST run from the project's `AGENTS.md` and `.agents/` files without loading this skill again.

## Use this skill only for

- `bootstrap`: initialize ACHP in a new/blank repository.
- `adopt`: add ACHP to an existing repository without replacing existing project guidance.
- `upgrade`: update ACHP-managed protocol/template files while preserving project-owned state.
- `repair`: restore missing ACHP-managed setup files.
- `validate`: verify the ACHP installation and routing.
- `uninstall`: remove ACHP-managed repository setup while preserving project
  knowledge by default. The Workspace form is currently guarded; see the
  schema 0.2 boundary below.

For a management workspace, use the explicit command families:

- `workspace bootstrap|adopt|upgrade|repair|validate|uninstall`;
- `route create|adopt|list|validate|set-state|rename`.

Workspace commands use the exact supplied path and never climb to a Git root.
Route adoption registers and minimally annotates a Route while preserving its
existing `AGENTS.md`, `.agents/knowledge/`, references, and state.

Schema 0.2 boundaries are intentional: `workspace uninstall` currently refuses
to change files until a reviewed ownership plan exists. `route rename` updates
only the Route display metadata; it does not move the Route directory or rewrite
its path and content. Path-moving rename, split/merge, Endpoint replacement,
restore, and rollback are future migration contracts, not operations implied by
the current command list.

Do **not** use this skill merely because a project already uses ACHP.

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
7. Runtime capability observations stay local under `.agents/runtime/` and are not committed as universal truth.
8. Harness-specific compatibility is thin:
   - Codex/OpenCode can use `AGENTS.md` directly.
   - Claude Code gets a minimal `CLAUDE.md` import/router to `AGENTS.md`.
9. Existing `AGENTS.md`, `CLAUDE.md`, `.gitignore`, project docs, source, and Git history must be preserved.
10. The setup skill itself is not referenced by runtime instructions.
11. A Project Collaboration Workspace may be non-Git; source-state and endpoint
    claims remain explicit `unknown`/`unverified` until evidence is bound.
12. Root registry writes contain stable identity, lifecycle, and pointers only;
    dynamic Route state remains Route-owned.
13. `AGENTS.md` contains only startup-critical, always-on invariants. New
    material is admitted there only after real work demonstrates stable,
    cross-session value that cannot be reliably supplied by retrieved knowledge;
    concrete state and knowledge lifecycle remain in their authoritative
    Route/state/knowledge surfaces.

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
