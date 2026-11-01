# ACS 2.1.0 communication qualification

The frozen implementation `bd3e02ab39cc18c46a2e076fdfa76642497beff4` was exercised through real PostgreSQL,
normal authenticated MCP tools and actual Native APIs. The file digests in
`verification.json` bind the Runtime bytes used by all three integration scenes.
The evidence contains synthetic test summaries; raw model reasoning, credentials
and production message handles remain outside the public artifacts.

| Scene | Actual result |
| --- | --- |
| Reverse physical Native | Remote physical Linux Codex A → Windows-host WSL OpenCode B; two independent models; one default-maintenance Native prompt; B's own explicit related MCP reply; evaluator dispatch calls 0 |
| Restricted Shared | Windows Codex A and Linux OpenCode Native B, separate ordinary engineer credentials and Shared surfaces; one Native prompt; related reply satisfies A's original handle; evaluator dispatch calls 0 |
| Shared idle lifecycle | 11 live idle observations across a configured 120-second window; no model turns; owned cgroup empty after stop |
| Sustained transport | 600 configured active seconds in two phases, 2392 request/reply exchanges, 233 same-request retries, 88 third-party read denials; independent database identities/content/reply counts match |

Both model exchanges contain exactly two committed messages and one explicit
reply. `work_items` is absent. A Native acknowledgement is not substituted for
B's reply. Delivery ACK uncertainty is retained in the JSON; no duplicate
invocation was used to obtain a reply.

The Shared receiver pins the executable, schema, configuration and selected
agent/provider/model. Nine exact ACS permissions are allowed. Native shell,
file and task tools, wildcard ACS permissions, extra MCP entries and plugins
are rejected. Actual Native effective permissions and real Session readback
are checked. The tested cgroup policy is 128 tasks, 1 GiB memory, 100% CPU,
`NoNewPrivileges`, `ExitType=cgroup` and group-wide termination. The two-second
local idle lease is refreshed before invocation; the signed transport
observation has a separate 15-second bound. There is no terminal collector or
Native execution-event subscription.

Authorization and enrollment now use stable shared reads, retaining revocation
fences. Shared signed delivery reconstructs only the exact committed sender
within the current Authority. One-use registration challenges stay fresh through
commit; the requested Endpoint lease remains bounded by the current Node,
Runtime and Grants. Generated SDK data stays in private state, separate from the
pinned operator configuration. Linux listener scans tolerate a foreign process
exiting. Proven owned capacity is stopped before releasing its claim, including
expired lifecycle authorization. Quiet Native output is drained without waiting
for a full buffer; a real open-pipe regression verifies short output.

The sustained peers use real stdio MCP processes and PostgreSQL with
`message_only`; they are scripted. This measures communication transport,
not model throughput. The round-trip p50/p95/p99 were
0.539/0.859/1.141 seconds in this run.
The midpoint starts new A/B/C MCP processes, retries the original request key
and reads the existing related reply. Final readback checks all message IDs,
content hashes and reply counts against the external expected manifest.

Focused Windows PostgreSQL/HTTP regressions: 119 passed, 9 skipped. Private
Linux component checkout: 911 passed, 775 skipped. Skips retain their actual
missing environment/historical Gate conditions. GitHub CI is recorded against
the final publication candidate separately.

Failed smoke/model attempts are summarized in `verification.json`; they are
not counted as qualification passes. Two Windows direct Python-to-WSL-database
load attempts stopped late after 2,084 and 2,243 completed exchanges. The test
database container did not restart. That direct Windows test path remains
unqualified; the successful sustained run uses the actual Linux Runtime path.
Raw failed evidence remains private to avoid publishing model reasoning.

This qualification covers the named OpenCode 1.18.34 Linux Shared receiver.
It does not certify all Harness/OS combinations, a new Codex Shared Native
permission profile, or sustained model load. Engineering release publication
does not create a historical formal Gate acceptance record.
