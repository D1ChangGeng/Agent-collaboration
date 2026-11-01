# ACS v2.2.0

The Linux Codex receiver now supports a pinned 0.163.0 Shared communication
profile with the normal ACS tools. Startup verifies actual permission, feature,
MCP and Session readback. Explicit private environment references connect the
ordinary recipient and approved model provider. See the
[Shared Codex configuration contract](runtime/SHARED-CODEX.md).

Codex Shared readiness previously spent its two-second local lease reading
history and rechecking authorization. A final status read now starts the lease
after those checks. Invocation still rechecks the Native target, current
authority and dispatch marker. Each owned capacity gets fresh lifecycle
operation identities, so a replacement cannot reuse an old spawn receipt.

Windows direct-to-WSL tests also captured PostgreSQL connections closing during
startup. Connection opening now has a default five-second timeout and at most
two short retries for narrowly identified pre-query disconnects. Explicit DSN
timeouts, TLS and authentication settings are retained. SQL, transaction commit
and Native effects are never replayed by this recovery. A real TCP fault test
checks ordinary MCP communication and exact message/reply counts after two
startup disconnects. Container readback showed no database restart or OOM;
the precise lower-level cause of the WSL disconnect remains unassigned.

An established database connection failure returns `unknown` with unavailable
evidence, rather than claiming the authority rejected the request. An admitted
send retains its original request key and explicit recovery guidance. The
sustained client follows this contract with bounded same-key retries and
independent exact readback; it does not bypass authorization or retry Native
effects. Post-commit observation-loss coverage verifies one committed message
after recovery with the original key.

Actual qualification includes a Windows Codex A to physical Linux Codex Shared B
exchange, independent ordinary credentials, one Native call, the explicit
related reply and OS permission positive/negative probes. Windows direct MCP
to WSL PostgreSQL sustained tests use scripted peers and independent final data
readback; they do not measure model throughput. The
[evidence report](../integration_evidence/acs-codex-shared-20261101/REPORT.md)
records durations, failures, retests and limits.

CI now labels its candidate archive with the installed product version.
No database migration is required from v2.1.0. Use the existing verified updater
and signed receiver upgrade paths, preserving data, credentials, keys and
journals. Enabling Shared remains an explicit operator configuration; upgrading
an Owner installation preserves its selected environment.
