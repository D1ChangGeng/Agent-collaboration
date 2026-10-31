# Runtime project identity adoption

The optional Runtime identity extension preserves Workspace schema 0.3, the
existing Root ID, Route registry, project guidance and knowledge. It writes a
stable `project_id` to `.agents/manifest.json` and an `ACS-PROJECT` managed block
in the Management Root's `AGENTS.md`.

## Locate the current Management Root

The Agent inspects the selected Management Root, its Project/Root identity,
Route registry, instructions and knowledge. Use the path spelling of the machine
holding these files and verify access through its connected OS account.
A correctly initialized Management Root can be nested in Git or held in a
standalone directory. Owner registration stores its current machine and directory.

Source inspection is an Agent decision when the task depends on product files
or a specific version. Use available machine, native or Git readers and record
the source actually observed. [Source discovery](SOURCE-DISCOVERY.md) provides
an optional read-only Git checkout probe and the Shared Source export procedure.
Runtime deployment, management file location and product source location each
have their own observed identity.

Preview against the existing Management Root:

```text
python scripts/project_setup.py workspace adopt-runtime-project --root <management-root> --project-id <stable-project-id> --dry-run
```

Apply with a new rollback directory outside the Management Root, then validate:

```text
python scripts/project_setup.py workspace adopt-runtime-project --root <management-root> --project-id <stable-project-id> --rollback-dir <private-backup-directory>
python scripts/project_setup.py workspace validate-runtime-project --root <management-root>
```

The operation rejects conflicting identities, malformed markers and unvalidated
Workspace state. Repeating the same adoption is a no-op. Original bytes and
before/after digests are retained in the rollback directory. A failed write
restores files still owned by that attempted change; subsequent edits are
preserved. Explicit rollback verifies both backups and current target hashes:

```text
python scripts/project_setup.py workspace rollback-runtime-project --root <management-root> --rollback-dir <private-backup-directory>
```

## Owner Project registration

Install the optional Runtime package in the setup Python environment and use the
selected owner's private surface configuration. The registration bridge reads
its configured access mode; `runtime_project_registration` selects the current
file registration path for owner mode. Supply the existing Root Scope and
AgentSlot, a project display name and the explicit goal of each registered Route:

```json
{
  "schema_version": "acs-runtime-registration/1",
  "scope_id": "<existing-root-scope>",
  "agent_slot_id": "<existing-root-slot>",
  "name": "Project display name",
  "route_goals": {"<existing-route-id>": "Explicit existing Route goal"}
}
```

Project and Root identity come from the initialized Management Root. The plan
records its absolute directory, `machine_id: local`, instruction paths and
knowledge index paths. `local` uses the OS account executing the registration
and current file service. Use that machine's own directory namespace. A standalone
Management Root registers through the same entry point.

Preview validates the management metadata and reads current document contents.
Its digest binds Project/Root identity, management location, file inventory,
Route goals, catalog and private configuration:

```text
python scripts/project_setup.py workspace register-runtime-project --root <management-root> --runtime-config <private-config> --registration-spec <specification> --tool-catalog <catalog> --dry-run
```

After reviewing the plan, apply its digest. `--adopt-project-schema` explicitly
adopts the Project extension schema; use the matching installed schema for
ordinary registration. [Runtime adoption](UPGRADE-CONTRACT.md) records the known
Domain 1.14 and Project schema migration boundaries.

```text
python scripts/project_setup.py workspace register-runtime-project --root <management-root> --runtime-config <private-config> --registration-spec <specification> --tool-catalog <catalog> --expected-plan-digest <reviewed-digest> --adopt-project-schema
```

Apply rechecks the plan, admits the Project identity, configures current file
locations and registered Routes through their expected revisions, then reads
`load_project`. The readback reports the management machine/path, current
instructions and knowledge indexes, observed document facts and context
completeness. Existing identity conflicts require explicit reconciliation;
management instructions and knowledge retain their original bytes.

Reapplying equivalent registration observes existing records. A changed location
or document set gets a new preview and current context readback. For later
configuration, use `configure_project` to set, replace or clear `management`
and its document paths with the current Project revision. Daily file inspection
and changes use the standard machine file tools.

The Agent chooses the source version for each WorkItem. Owner `source_baseline`
may be omitted or null; an eligible `revise_work` can select, change or clear
that version. Review and acceptance use the commit/tree actually observed and
reported by the Agent with the candidate's recorded Evidence. Existing Source
records retain their explicit historical IDs and captured revisions. See
[Owner Runtime](OWNER-RUNTIME.md) for current context, source history and
acceptance.

## Shared Domain and Source registration

Commit and synchronize the adopted identity files first. The optional Runtime
package must be installed in the setup Python environment. An operator supplies
an existing Root Scope/AgentSlot/Grant and a private surface configuration with
explicit Source/CAS providers for the Root and each planned Route Scope. The
Grant needs project, Route, delegation, context, Source and Artifact permissions
for these operations; registration never enrolls or enlarges the Root Grant.

The registration specification is a JSON object:

```json
{
  "schema_version": "acs-runtime-registration/1",
  "source_root": "/absolute/source/checkout",
  "expected_commit": "<exact-commit>",
  "expected_tree": "<exact-tree>",
  "scope_id": "<existing-root-scope>",
  "agent_slot_id": "<existing-root-slot>",
  "name": "Project display name",
  "source_id": "source-root",
  "repository_identity": {"kind": "git", "name": "Project repository"},
  "route_goals": {"<existing-route-id>": "Explicit existing Route goal"},
  "skill_catalog_path": "docs/runtime/p2-mcp-tool-contract.json",
  "max_source_bytes": 16777216
}
```

`skill_catalog_path` and `max_source_bytes` are optional. Every registered Route
must have an explicit goal; there is no goal inference from a Session or host.
The plan is bounded to 32 Routes. A new Route Scope is `scope-` followed by the
SHA-256 of canonical JSON `[tenant_id, project_id, route_id]`; the deterministic
mapping must match the separately configured Scope providers.

Preview performs only filesystem/Git/config reads, without database access or
CAS creation. It requires a clean containing checkout at the exact commit/tree,
valid existing metadata, tracked context paths and explicit providers. It binds
the Source, preservation inventory, catalog and configuration in a plan digest:

```text
python scripts/project_setup.py workspace register-runtime-project --root <management-root> --runtime-config <private-config> --registration-spec <specification> --tool-catalog <catalog> --dry-run
```

After reviewing the plan, apply its digest. `--adopt-project-schema` is a
separate explicit opt-in for the current project extension schema; omit it when
the matching schema is already installed. Unknown schema drift is refused.

```text
python scripts/project_setup.py workspace register-runtime-project --root <management-root> --runtime-config <private-config> --registration-spec <specification> --tool-catalog <catalog> --expected-plan-digest <reviewed-digest> --adopt-project-schema
```

Apply rechecks the plan, composes Project/Route/Source/context registration in
one Domain transaction and reads back committed Root and Route context packs on
a separate connection. Existing identities, Route metadata and knowledge bytes
are preserved. Existing Runtime identity/lifecycle conflicts require explicit
reconciliation; there is no implicit reparenting or Scope migration. Root Source
uses `route_id: null` instead of inventing a Root-as-Route alias. Route Source
keeps its real Route ID and a distinct Scope. The Runtime reads the actual
registry and Route identity bytes before recording `management_source_state:
adopted` with the exact source revision and digests.

Reapplying an unchanged registration observes the same records. Changed Source
revisions require a new preview and refresh the Source/context readback.
A failed Domain transaction does not commit registrations, but already exported
immutable private CAS objects remain for audit/recovery; they are not accepted
Domain state and are not implicitly deleted. No command starts Harness execution
or a public listener, submits acceptance, commits Git, or publishes a release.

Filesystem adoption, Domain registration, Source admission and actual Harness
execution are distinct verification steps. The metadata operation alone does
not establish Runtime or P2 support.
