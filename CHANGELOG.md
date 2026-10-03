# Changelog

All notable changes to this project will be documented here.

## Unreleased

- Machine setup runs prerequisite and selected Harness probes concurrently,
  reuses static readback within an installation and validates the selected
  project context. Tool discovery batches one membership scan and transaction
  while retaining live permission checks.
- Sync sends and response waits observe their target condition by default.
  Optional caller timeouts return pending handles while durable dispatch,
  response tracking and notification continue; cancelled MCP waits release
  their observation workers.
- Message business expiry is derived from Work budgets, Scope/Team Policy and
  Grant horizons. Receipts report its effective value, and observation options
  can change when replaying a new Message command identity.

- Add connection clocks calibrated to authenticated PostgreSQL Authority time,
  complete connection and Runtime identity, bounded uncertainty and conservative
  expiry checks.
- Use monotonic execution budgets with Linux suspend handling, preserve compatible
  signed timestamp encoding, and bind admission and recovery to durable command
  identities and replay fences.
- Add IANA timezone presentation alongside canonical UTC data and PostgreSQL 16
  CI coverage for Authority, ledger, lease, receiver-domain, management and
  evidence behavior.

## 1.3.1 - 2026-10-03

- ChatGPT account setup uses the owner's external browser on their client
  machine. Agent navigation uses verified Harness control within the owner's
  given setup authorization. Required login, permissions, secret entry and
  connection consent remain owner confirmations.
- Guided account setup provides official links, exact pages and labels, actions
  and expected results, waits for owner completion and then verifies actual MCP
  calls. Public documentation retrieval proceeds independently and read-only.
- Installation guides and setup Skills carry the browser context and consent
  procedure alongside the existing automatic upgrade controls and stable launcher.

## 1.3.0 - 2026-10-03

- Release installations enable automatic upgrades by default, with an install
  opt-out and owner controls to enable, disable, inspect or immediately check
  the existing installation. Regular upgrades preserve an existing opt-out
  unless the owner explicitly enables automatic updates.
- Daily stable Release checks use an owner systemd user timer or cron, with
  background catch-up on new MCP connections and an hourly retry after errors.
- Automatic activation requires the same major version and unchanged license,
  schema, migration, provider and MCP catalog contracts. Archive and installed-file
  verification, locked environments, provider health and existing authorization
  checks protect activation.
- Stable local, SSH, WSL and Tunnel launch commands follow the active version
  for new MCP processes. Owned local Skills refresh transactionally and the
  previous version remains available for rollback; rollback holds the rejected
  version for review.
- The web setup helper can bind its Tunnel plan to a verified installation's
  stable launcher through `--installation-root`.
- Installation and recovery guides document update controls, observed scheduler
  state, remote client Skill maintenance and the first guided upgrade required
  for existing v1.2.0 installations.

## 1.2.0 - 2026-10-02

- The Release includes a standalone `acs_bootstrap.py` with the v1.2.0 default,
  covered by the same SHA-256 inventory as the ZIP and TAR archives.
- Machine installation explicitly records whether ChatGPT web access is enabled,
  skipped or deferred, and emits a private Tunnel setup guide with AI commands,
  owner authorization actions and actual connection verification requirements.
- Existing-project setup discovers the actual local, SSH or WSL Source checkout
  and its identity/revision before selecting a SourceBinding registration view.
- Copied setup Skills include installation and Source discovery guides with
  ownership checks for their nested documentation directories.

- Machine setup confirms a local Linux host, named SSH target or named WSL
  distribution before applying an installation, and binds the plan to its
  observed machine identity, owner account and home directory.
- Global Runtime setup runs independently of project selection. Users create
  or adopt project Management Roots through the setup Skill when needed.
- SSH/WSL installs Runtime services with a Runtime-only profile and returns a
  stdio connection descriptor for the selected client hosts.
- Bootstrap, discoverable setup Skill and onboarding share the machine-first
  installation workflow and report client handshake checks explicitly.

## 1.1.0 - 2026-09-29

Standard Release Bootstrap installation is now available for fresh machines
and controlled upgrades. The Bootstrap verifies the published archive and every
file manifest entry, installs into a versioned private directory, switches the
active version atomically, and retains a previous version for rollback.

### Included capabilities

- GitHub Release metadata and SHA-256 archive verification before installation.
- Safe ZIP/TAR extraction with path, link and file inventory checks.
- Versioned installation state with active/previous commit and tree readback.
- Project installation handoff from the verified Release directory.
- Bootstrap security tests and hosted CI coverage.

## 1.0.0 - 2026-09-27

The Agent Collaboration System v1.0.0 combines the setup Skill, Project
Collaboration Workspace model and authenticated Runtime MCP surface in one
guided distribution path.

### Included capabilities

- AI-guided local readiness inspection, guarded installation planning and
  owner-local PostgreSQL/Temporal service composition.
- Codex and OpenCode Skill installation with eight lazy Runtime knowledge
  modules and digest-based ownership checks.
- Project Management Root adoption, stable `project_id`, Route and Source
  registration procedures, and explicit Runtime context readback.
- Typed MCP tools for Project, Route, Team, WorkItem, messaging, Inbox
  continuity, Source reads and Review workflows.
- Single-user private ChatGPT MCP Tunnel profile with official OpenAI setup
  references and owner-scoped ACS Grant checks.
- Public README, Chinese README, first-use guide, troubleshooting guide,
  architecture diagrams, collaboration flow diagram and source-bound package
  manifests.

The release package records the exact source commit/tree, locked dependency
inventory, package file digests and archive SHA-256 values. Runtime support
claims remain bound to the named source, host, Profile, Grant and observed
readback evidence.

## 0.4.0 - 2026-09-09

Agent-readable lifecycle guidance and safety hardening.

### In-place refresh - 2026-09-11

- The default project layout keeps product code and a nested Management Root in
  one Git repository. Root documents, knowledge, and Route directories travel
  with the same repository-relative layout across local and remote clones.
- Nested Workspace setup maintains scoped runtime exclusions in the repository
  root `.gitignore`. Explicit Workspace upgrade consolidates known setup-only
  child ignore files while preserving user rules and existing identities.
- Management Root `AGENTS.md` includes a generated source-checkout binding. The
  relative path follows the actual nesting depth, and Git synchronization,
  pulling, staging, and commits use the source checkout as working directory.
- Setup preserves user guidance when adding the binding; malformed or changed
  bindings require review before writes. Legacy standalone adoption and repair
  retain their existing layout.
- Version remains `0.4.0` and Workspace schema remains `0.3`. The `v0.4.0` tag
  and release archives are refreshed together. Existing archive installations
  need a fresh download and reinstall to receive these changes.

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

- Current Windows suite: 111 tests, 106 passed and five symlink-related tests
  skipped because the process lacks the required creation privilege.
- Skill, quick, repository, Workspace, Route, and diff validation passed.
- Nested-layout tests cover real Git clones and linked worktrees, source-path
  resolution, ignore behavior, migration, dry-run, idempotence, and preservation
  of user-authored instruction text.

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
