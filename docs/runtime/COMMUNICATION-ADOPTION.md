# Communication archive adoption and recovery

Normal entry points validate storage without modifying it. Explicit operator
adoption uses `ProjectService.initialize()` in the existing installer path.
The additional archive schema has no dependency on a task lifecycle table.

For an existing deployment, inventory its actual current database and source
before selecting a cleanup. The following operator command is read-only by
default. The named environment variable contains the DSN; its value is never a
command argument or report field.

```powershell
python scripts/acs_communication_inventory.py --dsn-env ACS_OPERATOR_DSN --schema public --tenant-id TENANT --project-id PROJECT
```

The report distinguishes supported packet versions, existing project
associations, missing identity evidence, conflicts and retained pending/uncertain
delivery records. Its `plan_sha256` covers the source association facts. A legacy
sender Slot and recipient principal are not reconstructed from current names,
timestamps or a Native result. An unassociated packet remains in storage for
operator review.

After explicitly installing the archive schema, the same tool can apply the
reviewed index plan. This adds derived association rows only:

```powershell
python scripts/acs_communication_inventory.py --dsn-env ACS_OPERATOR_DSN --schema public --tenant-id TENANT --project-id PROJECT --apply --expected-plan-sha256 PLAN_SHA256
```

A changed source plan or conflicting existing association refuses adoption.
Repeated adoption preserves existing rows. No packet text, command identity,
reply relationship, delivery fence, Task data or Native artifact is rewritten or
deleted. Quiesce legacy writers before a real cutover; no background compatibility
worker keeps accepting new task traffic.

Keep both data and technical recovery evidence until legitimate replay risk is
resolved. Table-name similarity is insufficient to decide removal. The current
default adapters no longer load task execution modules, while legacy database
tables and Domain library code remain for the separately reviewed transition.
This procedure grants no production cleanup or environment-switch authority.

The isolated rehearsal uses real `pg_dump --snapshot` and `pg_restore` into a new,
owned database. It compares all table data before changing the clone. It then
revokes the old source and cloned Authority, marks snapshot-pending delivery
uncertain, installs a new read-only identity, and verifies original message,
reply and legacy packet readback after retiring task tables. A fixture Native
effect occurring after the snapshot is not replayed in the clone.

Database restoration alone cannot restore Native execution authority safely.
Actual recovery must also fence old writers and Nodes, preserve Node journals
and relevant artifact files, and review the actual source/Node generation before
enabling execution. The rehearsal does not certify a production failover or an
old-binary rollback after new communication writes.
