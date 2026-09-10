# Upgrade Policy

## Principle

Skill updates and project protocol upgrades are intentionally separate.

Schema 0.2 remains a read-compatible input, not a target for new schema 0.3
records. If `workspace adopt` or `workspace repair` discovers an unregistered
Route, or `route create` / `route adopt` would add canonical Route metadata or a
registry entry, the operation stops and requires an explicit Workspace upgrade
before writing. Read-only validation and no-op handling of already registered,
fully initialized legacy Routes remain available.

The same boundary applies to the Root registry itself: a schema 0.2 registry is
not extended with a schema 0.3-shaped entry. The upgrade operation must first
canonicalize the control-plane data, after which new Route writes use the
schema 0.3 shape.

Pulling a new version of this Skill must never silently rewrite projects that already use ACHP.

## Managed vs project-owned files

### Setup-managed

These may be replaced during `upgrade`:

- ACHP managed block in `AGENTS.md`
- ACHP managed block in `CLAUDE.md`
- ACHP managed block in `.gitignore`
- `.agents/README.md`
- `.agents/protocol/*`
- `.agents/coordination/roles/*`
- `.agents/coordination/templates/*`
- `.agents/knowledge/README.md`

### Project-owned

These are created if missing and then preserved during upgrades:

- `.agents/config.yaml`
- `.agents/coordination/PROJECT.md`
- `.agents/coordination/tasks/*`
- `.agents/coordination/handoffs/*`
- `.agents/knowledge/guides/*`
- `.agents/knowledge/decisions/*`
- `.agents/knowledge/observations/*`
- `.agents/knowledge/archive/*`

The repository-mode `config.yaml` is project-owned protocol configuration. Its
version may remain at an older project value when an existing installation is
upgraded; it is not rewritten as a Skill release marker. New repository
scaffolds use the current Skill release identity, while Workspace scaffolds use
the current Workspace protocol release.
- Harness/session capability observations (local context; no project file)

For a Project Collaboration Workspace, the same distinction applies at the Root
level:

The default v0.4.0 layout places the management root in the same project Git
repository as product code:

```text
Project Git Repository / Source Checkout Root
├── Product code
├── ...
└── Nested Management Root
    ├── AGENTS.md
    ├── .agents/
    └── Route directories
```

Management documents, knowledge, and Routes share project Git commits with
product code. Local and remote clones retain the same relative layout and
require explicit Git synchronization. The manifest records
`collaboration_root_mode`; Git carries the layout. Standalone Workspaces remain
supported for compatibility.

Legacy manifests missing the mode remain unchanged during `adopt`/`repair`.
Explicit `workspace upgrade` inside Git migrates a known setup-only child
ignore to the repository-root `.gitignore`. Custom child rules require reviewed
manual consolidation; the operation refuses writes until that is resolved.

### Workspace setup-managed

The Workspace setup may maintain Root `AGENTS.md`, the thin `CLAUDE.md` route,
`.agents/manifest.json`, Root protocol files, `ROOT.md`, the handoff placeholder,
and the Root knowledge README. The CLI keeps the exact management root; its only
parent write is scoped runtime exclusions between
`# ACHP-NESTED:<relative path>:BEGIN` and `# ACHP-NESTED:<relative path>:END` in
repository-root `.gitignore`. Preserve every existing parent block and rule.
Nested roots have no child `.gitignore`, and parent repository scaffolding is
not required. Compatibility standalone roots keep their own ignore boundary.
Review ownership conflicts before any write.

Nested Management Root `AGENTS.md` also carries an
`ACHP-SOURCE-CHECKOUT` managed block. Setup renders the source checkout path
relative to the management directory and sets the effective working directory
for Git synchronization, pull, staging, and commits to that source checkout.
Repair may add a missing block while preserving existing guidance. A changed
or stale block requires review before any setup writes.

### Workspace project-owned

`PROJECT.md`, `ROOT-BASELINE.md`, and `routes.yaml` are Root-owned project files.
Route directories, Route `AGENTS.md`, Route knowledge, references, and any
existing Source State records are Route-owned. New Routes create Source State
only when verified source facts require a durable Route record. Explicit
Workspace/Route operations may
reconcile stable registry entries in `routes.yaml`; that is a control-plane
update, not permission to replace the file with a generic template or to rewrite
Route content. The current `routes.yaml` file is deterministic JSON text with a
`.yaml` name (JSON is a YAML 1.2 subset), and remains the single canonical
registry.

Workspace upgrades do not perform Route semantic migration. In particular, they
must not move Route directories, merge or split Routes, replace Endpoint
bindings, or reclassify Route knowledge as part of a generic upgrade. The
explicit `route upgrade` command is the narrow metadata migration boundary: it
projects recognized schema-0.2 fields into the schema-0.3 identity shape,
preserves unrecognized extension fields, and leaves Route-owned content alone.
`set-state` and `rename` then update the Root registry only.

## Upgrade steps

1. Preview with `--dry-run`.
2. Review version/changelog impact.
3. Run `upgrade`.
4. Validate.
5. Review Git diff.
6. Commit as a distinct protocol/setup change.
7. Relay repository sync requirements to other active clones/sessions.

## Backward compatibility

Breaking changes to:
- relay envelope schema;
- task/handoff semantics;
- knowledge location;
- repository sync contract;

must be documented before release and should include a migration strategy.

Schema 0.3 also keeps the following boundaries explicit:

- Route `rename` changes display metadata only; path-moving rename is a future
  migration operation.
- Split/merge, Endpoint replacement, restore, and rollback are future migration
  contracts, not current upgrade side effects.
- Standalone non-Git Workspaces remain supported for compatibility; missing
  source and endpoint facts remain explicit `unknown`/`unverified` values.
- Manifest ownership inventories and hashes are optional setup-integrity
  metadata. They are not collaboration lifecycle or Session recovery state.
- A missing baseline pointer can be derived from the fixed Root contract path;
  a present non-default pointer is rejected rather than redirected.

## Uninstall

For a source repository, default uninstall removes only setup-managed
files/blocks and preserves project-owned collaboration/knowledge data.

For a Project Collaboration Workspace, `workspace uninstall` currently refuses
to run and makes no changes. A Workspace Root contains ownership and Route
registry state that cannot be safely removed by the generic repository uninstall
path. Removal, including any future purge mode, requires a separately reviewed
ownership plan and an explicit migration implementation.

`--purge-data` is intentionally explicit and destructive.
