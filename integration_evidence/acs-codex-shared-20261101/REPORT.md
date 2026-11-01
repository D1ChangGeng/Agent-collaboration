# Codex Shared Native and Windows direct-to-WSL qualification

Product 2.2.0; frozen Runtime baseline `ae10fac6eb47f8e5616ddb241176058589150595`.
The JSON records SHA-256 for every tested Runtime Python/SQL file. Both Native
runs and both load runs must match those exact bytes. Evidence contains no
production message handles, credentials or model reasoning.

| Scope | Actual result |
| --- | --- |
| Physical Codex Shared | Two independent ordinary engineer models, Shared on both sides; one signed Native `turn/start`, evaluator dispatch 0; exactly two committed messages and one explicit own-author related reply |
| OS permission executor | Allowed file read; write denied by read-only filesystem; scope-external read denied; host network positive and sandbox network denied |
| Shared idle | 25 live idle/owned observations across 120 configured seconds; no model turns; owned cgroup empty after stop |
| Windows transport 1800 s | 6544 complete exchanges, 653 original-key retries, 256 third-party denials, 0 bounded unavailable-result recoveries; exact independent final data readback |
| Separate 600 s error diagnostic | 1920 exchanges, 0 unavailable-result recoveries; same immutable Runtime and independent final readback |

The Native receiver pins Codex 0.163.0, generated protocol schema, private
configuration and selected permission profile. Startup observes the actual
read-only/network-disabled sandbox, six disabled features, connected MCP with
the eight project-scoped communication tools, cwd and Session identity. The
allowlist also contains Owner-only `list_projects`, absent in Shared discovery.
The real command probes use the administrative permission executor with the
same profile; ACS does not add that endpoint to the model's tool surface.
The reviewed host sandbox helper is required. Sandbox initialization failure
is not counted as a successful permission denial.

The cgroup enforces 64 tasks, 1 GiB and 100% CPU, with NoNewPrivileges, cgroup
lifetime and group-wide stop. No terminal collector or Native event
subscription participates in reply matching. B uses its own ordinary ACS
credential and explicit reply relationship.

History and authority checks precede a final current-status request; its
round-trip remains inside the two-second local lease. The independent review
raised the slow-response case. A dedicated calibrated-clock regression proves
that a response after 2.1 seconds expires and permits zero Native calls. Starting
a new lease after that old request returns would overstate its freshness.

Windows direct PostgreSQL traffic captured startup EOF while the isolated
database stayed running without OOM/restart. Opening a connection now retries
only narrow pre-query disconnects, at most three attempts with short backoff;
the default timeout is 5 seconds unless explicitly configured. No query, commit
or Native effect is replayed. Established connection errors retain unknown
outcomes and original validated request keys. A real TCP proxy closes two
startup handshakes and verifies normal MCP recovery. A separate controlled
post-commit observation loss verifies that same-key recovery yields exactly
one committed message, not a new send.

The sustained clients implement the documented bounded recovery policy. They
record expected identities before sending, reuse the exact key for retries,
restart all stdio peers at the midpoint, recover the original reply, and then
compare every persisted message ID, content hash and reply count against the
external manifest. Repeated bodies with new keys remain distinct. Unauthorized
reads remain denied. `work_items` is absent in these fresh test Authorities.
This is scripted MCP/PostgreSQL load, not a claim of sustained model throughput.
The 1800 s round-trip p50/p95/p99 were
0.774/1.519/1.986 seconds in this environment.

Test counts and skipped prerequisites are recorded independently in the JSON;
the suites overlap and are not summed. Earlier failures are retained with their
scope. The exact lower-level cause of intermittent WSL disconnects remains
unassigned; later recovery does not erase those observations. Other Codex
versions, Windows Shared Native, full cross-Harness/fault matrices and larger
loads require their own qualification. Production cutover is a separate record.

Qualified commands used `pytest runtime_tests/test_communication_remote_native.py::test_physical_signed_receiver_and_independent_reply[codex]` with explicit real-remote/model/Shared/Codex opt-ins, the same fixture in `lifecycle` mode, and `pytest runtime_tests/test_communication_sustained.py` with four workers and 600/1800 active seconds. All use isolated PostgreSQL and private credential references. The long run has no diagnostic wrapper; the separate 600-second run logs private errors only.
