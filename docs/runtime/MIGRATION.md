# Runtime adoption and rollback

Runtime adoption adds a versioned execution profile to an existing project. It
preserves the setup Root/Route identities, knowledge and source history.

## Baseline inventory

Run the source setup audit from the source checkout, using a new ignored output
directory on each run:

```text
python tools/bootstrap/audit_setup_baseline.py --output agent-collabration/.agents/runtime/bootstrap/audit-N --include-tests
```

The report records fresh subprocess commands, exits, configuration digests,
source HEAD, permissions observations and SHA-256 inventory of tracked files.
Keep it private: raw outputs contain workstation paths. The audit does not read
credential values, adopt a database, enroll a Node or start a Runtime. It rejects
an existing nonempty evidence directory so earlier observations remain intact.

Record source relationships and external Session references separately with
their observation class. A Git history or Source Snapshot remains the source
authority. A legacy transcript is imported evidence, not verified domain truth.

## Explicit switches

| Switch | Precondition and read-back |
|---|---|
| Setup schema | Existing workspace dry-run, ownership conflicts resolved, validation and preserved user bytes. |
| Runtime schema | Versioned PostgreSQL migration, backup/export, migration checksum and actual schema revision read-back. |
| Runtime execution | Named profile, authorized resources/budget, process owner and version read-back. |
| Node enrollment | Verified machine ownership, scoped key reference, trust/incarnation and revocation test. |
| Harness binding | Scoped grant, installed version probe and actual Session/Runtime binding receipt. |
| Source/artifact transfer | Separate permission, destination policy, input/output digest and receiver read-back. |
| Hosted storage or host autostart | Separate product/operational authorization; excluded from default local test adoption. |

The currently implemented setup command is
`python scripts/project_setup.py workspace upgrade --root agent-collabration --dry-run`.
Runtime migration and operation commands must come from the implemented Runtime
version and its evidence. Do not substitute a setup metadata command for Domain
adoption.

## Cutover checks

Before a domain authority cutover, drain new commands, checkpoint existing
operations, export Domain state and Provider references, preserve blob manifests,
and record old grants/incarnation. Verify backup digests and perform a restore
exercise in isolated resources. Commit the new authority binding only after the
new instance is consistent, and invalidate old grants/fencing generations at the
protected resource entry points.

Import existing coordination as versioned Message, WorkItem, Evidence and Binding
records under authenticated import commands. Preserve source and provenance;
import alone does not accept work or verify capabilities. Export projections can
be rendered into Markdown, but free file writes cannot mutate authoritative
Runtime WorkItems or AcceptedState.

## Rollback

Stop new admissions to the candidate authority. Export all newly committed
durable state, events and outbox/operation markers before reverting. Preserve
the failed attempt and uncertain effects for read-back. Restore the old source
and references from the recorded baseline; never reset or delete user work to
simulate a rollback. Reconcile existing real effects before any retry and issue
a new incarnation/generation under an explicit authorized recovery command.

The setup-only bootstrap introduces no production authority and starts no host
autostart service. Reverting its tracked contract/router changes restores the
previous setup view. Private audit evidence stays available. Once a Runtime
authority has committed operations, reverting Git alone is insufficient: use
the Runtime export/drain/restore procedure and retain the audit trail.
