# Changelog

All notable changes to this project will be documented here.

## 0.4.0 - 2026-09-09

Agent-readable lifecycle guidance and safety hardening.

### Added

- Operating Guide, Capability Matrix, and Scenario Matrix references for
  observe-before-ask decisions, natural-language intent interpretation, and
  conservative capability reporting.
- Read-only Workspace Route candidate listing and explicit repeatable
  `--include-route` selection; unregistered candidates are no longer silently
  claimed by ordinary Workspace adoption.

### Changed

- Repository setup uses the exact supplied path by default; containing Git-root
  discovery is opt-in with `--git-root`.
- Repository bootstrap, adopt, repair, upgrade, and validation now enforce
  clearer ownership boundaries, managed-content drift checks, and safer
  atomic file replacement.
- Workspace and Route validation require the complete Route scaffold and report
  failures, conflicts, dry-runs, and applied writes truthfully.
- Route creation now refuses existing unregistered paths; Route adoption
  preserves existing metadata identity, previews partial scaffolds, and creates
  only missing canonical setup files.
- Route-targeted operations validate the selected Route independently; a
  missing sibling remains visible to Workspace-wide validation without
  blocking unrelated Route work.
- Workspace, Route, and candidate-listing entry points reject symlink,
  junction, and reparse aliases instead of following them.
- Repository, Workspace, and personal Skill upgrades refuse unproven or drifted
  managed content and preserve project-owned bytes for review.
- Skill installation uses an explicit payload, ownership marker, content digest,
  staging replacement, and fail-closed handling for unknown destinations.

### Boundary

- v0.4.0 does not add Session attach, Endpoint replacement, SSH adapters,
  direct relay, collaboration migration, checkpoints, or runtime recovery
  state. Those remain outside the current setup Skill.

### Verification

- 93 unit tests passed; four Windows symlink tests were skipped because the
  current process lacks symlink-creation privilege.
- Skill validation, quick validation, Python compilation, repository setup
  validation, knowledge index/check validation, and diff validation passed for
  this release candidate.

## 0.3.0 - 2026-09-07

Minimal Workspace persistence model and compatibility release.

### Changed

- Root registry writes now keep only Route identity, canonical path, display
  name, and lifecycle status; Route metadata keeps stable identity and its
  explicit Root contract.
- Route Source State is created only when independently verified source facts
  have durable cross-Session value; fresh Routes no longer receive an empty
  unknown record.
- Harness, Session, live Endpoint, process-liveness, and temporary capability
  observations remain in the current execution context, while Git/source state
  and durable knowledge retain their own authoritative facts.
- Schema 0.2 input remains readable, and explicit upgrade is the boundary for
  canonicalizing legacy metadata and managed blocks.
- Validation now enforces strict schema, JSON, path, marker, ownership, and
  compatibility boundaries for the reduced state model.

### Verification

- 67 unit tests passed, together with Skill validation, compilation checks,
  repository setup validation, knowledge index/check validation, and a clean
  diff check.

## 0.2.0 - 2026-09-06

Project Collaboration Workspace and Route baseline.

### Added

- Explicit non-Git Project Collaboration Workspace setup and validation.
- Stable Root manifest, Root↔Route baseline, Route registry, and source-state evidence schema.
- Route create/adopt/list/validate/set-state/rename metadata operations.
- Always-on `AGENTS.md` admission and natural-evolution boundaries propagated
  across repository, Workspace, and Route scaffolds.
- Initial baseline semantics with explicit unknown/unverified values.
- Route-preserving, idempotent migration fixtures and ownership checks.
- Workspace-scoped relay, Git-sync, capability, and knowledge-boundary scaffold.
- Fail-closed validation for malformed manifests, registries, route metadata,
  path collisions, managed-file drift, and custom registry locations.

### Compatibility

- Legacy repository `bootstrap` / `adopt` / `upgrade` / `repair` / `validate` /
  `uninstall` commands remain available.
- Existing Route `AGENTS.md` and `.agents/knowledge/` content is preserved;
  Route semantic migration remains an independent follow-up operation.

## 0.1.0 - 2026-09-05

Initial public-ready scaffold.

### Added

- Setup-only portable `SKILL.md`.
- Harness-neutral ACHP project scaffold.
- Capability-based session relay policy.
- Manual user relay as a first-class baseline transport.
- Explicit Git Push/Pull handoff contract.
- `.agents/knowledge/` durable knowledge plane.
- Thin Claude Code `CLAUDE.md -> @AGENTS.md` compatibility route.
- Cross-harness personal Skill installer.
- Idempotent project bootstrap/adopt/upgrade/repair/validate/uninstall CLI.
- Unit tests and GitHub Actions validation.
- English and Simplified Chinese documentation.
