# First-entry identity and Root management verification

Implementation: `a99000ac40662127f63e56b4407d3c5ea3c1e24f`, tree
`31a7622e4f220e379a3a2c2f16bbd7906e993b54`, based on
`61bea50284665ee3c2a10785169b73ff104e11e4`. This is a source candidate; the
published production deployment remains v2.2.0. Aggregates and exact tested
Runtime byte fingerprints are in [verification.json](verification.json).
Core repair commit is `2908aea`; the final result/description contract is in
`4739539`, the compatibility-entry Gate check is in `759544f`, and effective
Slot identity / existing peer-manager protection is completed in `a99000a`.

S00 gives Project communication grouping/isolation duties and Root management
and context-source duties. Existing storage pairs them one to one. The repair
uses one `configure_root` operation over existing registration and team
configuration, retains stable identities/history, and attaches existing current
files when requested. A Client establishes a Root without a synthetic Client
Slot or a separate Project admission operation. Existing bound Root managers
configure their Root. The [Root contract](../../docs/runtime/ROOT-MANAGEMENT.md)
records the actual role boundaries and compatibility entry.

Actual source changes include authenticated `read_profile.actor` identity,
current role/Scope/manager/address context, communication follow-up actions,
live role/Grant/Slot/Scope checks, matching discovery/call management eligibility,
OAuth narrowing of discovery and context, nested configuration validation,
atomic concurrent Root setup, and safe conflict/reply guidance. Retired Work and
Review queries no longer appear in the normal actor context.

| Verification | Passed | Skipped | Failed / errors |
|---|---:|---:|---:|
| Windows PostgreSQL, stdio, HTTP and communication/configuration regression | 121 | 1 | 0 / 0 |
| Windows final actor/result contract, four-role stdio and HTTP regression | 25 | 0 | 0 / 0 |
| Linux Runtime components | 939 | 815 | 0 / 0 |
| Linux PostgreSQL, stdio, HTTP, Shared permission and current-file regression | 152 | 1 | 0 / 0 |
| Effective Slot / existing peer-manager matrix, included in final suites | 8 | 0 | 0 / 0 |
| Installed wheel, four separate actual stdio processes | 1 workflow | 0 | 0 |
| Independent actual Codex models | 4 Sessions + 3 same-Session continuations | 0 | 0 |
| Tool/result/compatibility contract checks | 10 | 0 | 0 / 0 |
| Local full Gate tooling, with absent host user-runtime directory | 119 | 0 | 0 / 5 |

The broad Windows and both Linux runs are pinned to final implementation
`a99000a`. The separate 25-case identity/result contract check records its
earlier `4739539` slice. The final model and installed-wheel checks below use
the final unchanged Runtime bytes.

The component run intentionally leaves environment-dependent PostgreSQL,
Temporal, systemd, Native and platform-specific tests skipped. PostgreSQL runs
use the separately guarded isolated test database. Their opt-in independent
model experiment is skipped because the explicit four-model workflow below
qualifies this change separately. Skips are not acceptance passes. Existing MCP
subscription tests emit deprecation notices for the retained SDK compatibility
method; their authorization/reconnect assertions pass.

Four separate Codex CLI 0.166.0-alpha.5.1 model contexts, configured with
gpt-6.1-sol and the explicitly authorized test Provider, each connected through
its own ACS MCP process and trusted role binding. The Client first identified
itself as Client, established the Root and its real collaborator configuration,
and messaged that Root. Root created a Route and configured its manager. The
Route manager configured the ordinary collaborator. Each recipient used its
own ordinary `send_message` to reply and, where appropriate, send the next
delegation. The evaluator provisioned trusted credentials from the committed
bindings and launched model processes; it did not send their messages or
manufacture replies.

| Actual model | First-entry level | Explicit associated response | Continued original Session |
|---|---|---|---|
| Client | client | Received Root's response | Same actual thread ID; Client identity retained |
| Root | root | Replied to Client; received Route response | Same actual thread ID; Root identity retained |
| Route manager | route | Replied to Root; received ordinary Agent response | Same actual thread ID; Route identity retained |
| Ordinary collaborator | agent | Replied to Route manager | First Session exercised; no separate continuation claim |

Independent database checks found exactly six committed messages, three explicit
reply relationships, three configured collaborators and no Work table. Separate
transcript checks verified the actual authors and reversed peer pairs for
Client↔Root, Root↔Route and Route↔ordinary Agent, plus real reply readback in each
of the three resumed Sessions. The workflow took about 353 seconds. It used
`message_only`; ACS Native invocation count was zero. Actual CLI thread IDs were
observed, while no receiving Native Session was fabricated or declared ready.

The built wheel was installed into a private directory. All packaged Runtime
bytes matched the tested source. Four new stdio processes using that installed
package repeated the role configuration chain and six-message/three-reply
workflow. These peers were scripted and are recorded separately from the actual
model test. Ruff and Git whitespace checks pass. The new PostgreSQL/stdio/HTTP
tests are included in GitHub CI.

The first GitHub run passed its complete PostgreSQL selection (439 passed,
12 skipped), then failed the old assertion that every catalog entry belongs in
a normal tool group. The revised check requires an exact, disjoint and complete
partition of normal tools and the declared executable compatibility entry. Its
ten contract checks pass. The local full Gate run has five errors because this
host lacks the user runtime directory required by unchanged bus-attestation
tests; all five follow the unchanged `gate_runner.py` / `test_gate_runner.py`
paths. No fake user bus or production environment adjustment was introduced.

Final identity counterexamples also exposed two implementation defects: the
second Slot under one Principal could lose its context because context reads
used the historical membership key, and a Root manager could demote an existing
peer by requesting ordinary-role fields. Context now reuses the existing
`CONTACTS` view used by message addressing; management checks the resolved
caller address and the target's current role. Eight Owner/Shared cases verify
explicit and uniquely resolved Slots, separate authors with a shared Principal
and Grant, ambiguous-binding rejection, peer-demotion rejection and legitimate
self-management. A replaced legacy Owner binding also rejects. Shared context
read permissions are explicitly granted in these tests, preserving the
distinction between responsibility and authorization.

An intermediate parallel Windows run encountered PostgreSQL connection
timeouts, including fixture setup and one concurrent send. Direct Linux
readback showed few database sessions rather than a full connection limit.
The final Windows suite was rerun after separating the bulk database phases and
passed 121 cases. This establishes the reported run; the transient Windows/WSL
test-transport cause was not independently resolved or presented as a product
load qualification.

Earlier failures remain part of the evidence boundary. The first actual model
run confused team and Route revisions and could not recover from the sparse
error. A later model correctly encountered rejection when associating a
third-party delegation with its Client's request, but lacked a corrective hint.
Both prompted code/schema/error-contract repairs before the final run. An
interim run completed the communication and continuation sequence while source
was still changing; its source-stability check rejected qualification. The
reported final run verified unchanged source throughout. The initial Linux
stdio fixture also failed its private-file permission check; the fixture now
sets the required mode, and the final actual protocol run passes.

An exploratory broader Windows selection produced 11 failures and one setup
error. The same failures/error were reproduced on the unchanged baseline:
retired Work/role assertions and Linux-only backend/Windows newline assumptions.
They were not converted into passes by restoring old task semantics. The
relevant current-file tests pass in the final Linux integration run.

This evidence qualifies Owner role onboarding and message-only model
communication. Shared narrowing is covered by real PostgreSQL/HTTP permission
tests, rather than a new Shared model Harness qualification. Physical Native
invocation, browser/public TLS ingress, production upgrade and formal release
are outside this candidate's acceptance claim. Private credentials, model
reasoning, actual thread IDs and message handles remain in local private
evidence; this report publishes only aggregates and source fingerprints.
