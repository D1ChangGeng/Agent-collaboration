# Changelog

All notable changes to this project will be documented here.

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
