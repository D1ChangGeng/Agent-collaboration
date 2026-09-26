# P1 Surface parity component evidence

The isolated component at `7f18640f3dac8f207aec2be4684ba7c1a5955244`
submits one WorkItem creation command through the actual MCP process, then
replays the exact command through CLI and loopback HTTP. All three return the
same Domain operation ID. Changing the source baseline under the same command
identity produces an HTTP idempotency conflict. PostgreSQL contains one
WorkItem, command-dedup row, Domain event, operation and Outbox record.

The component uses owner-only temporary files for the scoped PostgreSQL DSN,
transport credential and Surface configuration. Child process environments do
not contain the credential or DSN. They are removed after the MCP, CLI and
HTTP processes finish. The Linux real-PostgreSQL integration test exited 0;
its owner-only log SHA-256 is
`423b1d0e014eb1eab96f4420f7b344c2615be505dd574b756ac884826ca74f2d`.
Postflight confirmed a clean source checkout, zero non-system PostgreSQL
schemas, no matching temporary Surface directory and no remaining Surface
process. Ruff passed. The Windows collection test skipped because this
component requires POSIX owner-only file references.

This result is component evidence. The P1 Surface Parity Gate scene remains
`NOT_RUN`. The current Gate runtime profile declares loopback PostgreSQL and
Temporal providers, but does not yet bind the additional run-owned HTTP
listener or its termination into the six-layer scenario readback. The same
command must also be tied to the Gate's WorkItem/Message/Attempt lineage on
one fixed source, Machine and profile before the scene can be promoted.
