# P1 real-resource probe profile

This harness prepares executable evidence commands for the 18 P1 scenarios.
It does not write a formal Gate. Eleven scenarios currently have an actual
fixed-identity Runtime lineage adapter: `P1-DOMAIN-TRANSACTION`,
`P1-AUTH-REVOCATION`, `P1-COMMAND-DEDUP`, and `P1-INBOX-ACK-LOSS`.
`P1-CORE-RESTART`, `P1-NODE-RESTART`, `P1-PROVIDER-RESTART` and
`P1-LEASE-FENCING`, `P1-UNCERTAIN-EFFECT`, `P1-STALE-BASELINE` and
`P1-PARTIAL-ARTIFACT` are the remaining adapters. The other 7 have no runnable command and remain
`NOT_RUN`.

Each runnable scenario commits its own command, operation, event, Outbox,
message and receipt lineage in a dedicated PostgreSQL schema. It records
Node and Driver observations in a private SQLite journal and emits six
separately read-back probe results. The Gate-observed Machine ID is used by
the Node Journal and must match the result, Node boot/journal, and PostgreSQL
DeliveryAttempt selection on readback. For all scenarios except Provider restart,
the distinct Temporal workflow ID is the delivery operation plus `:temporal`:
it is an auxiliary recovery observation of the same scenario identity and
does not claim that Temporal invoked the Delivery dispatcher. Provider restart
uses the actual `acs-delivery/<operation>` Workflow and persists its run ID in
the Domain operation.

`P1-AUTH-REVOCATION` revokes the actual Grant after an authorized send and
requires blocked dispatch, zero Node messages, zero Driver calls and zero
Inbox projection. `P1-COMMAND-DEDUP` repeats the exact command, rejects a
changed packet under the same command identity, and checks the committed
dedup hash, one event/operation/Outbox, and one Driver call. `P1-INBOX-ACK-LOSS`
loses the transport ACK after Node commit, then recovers through a second
DeliveryAttempt and requires one Core Inbox projection and one Driver call.
The existing accepted Runtime test selectors remain the catalog reference;
the runnable probes execute the same real Runtime APIs with a scenario-fixed
identity and direct fault hook. A selector alone is not evidence.

`P1-CORE-RESTART` starts a separate Core process with only the owner-only
profile path and a digest-bound context file. The process exits at code `83`
after PostgreSQL commits a prepared DeliveryAttempt and before it can contact
the Node or Driver. A replacement Core resumes that same attempt and obtains
one Node commit and one Driver call. Readback checks the child's stopped PID,
private context digest, prepared attempt identity and final PG/SQLite state.

`P1-NODE-RESTART` first commits a `message_only` Inbox at the original Node
and loses its transport ACK. A separate process reopens the same Node journal
under a new boot, rebinds revision 2 and projects the same message through a
second DeliveryAttempt. The old and new boot selections, unchanged Node
receipts, one Core Inbox projection and zero Driver calls are read back. If the
child result survives but its parent proof write does not, recovery uses the
actual PG/SQLite state and records that the exit code was not observed.

`P1-PROVIDER-RESTART` submits one actual `acs-delivery/<operation>` Temporal
Workflow. Its first Worker process exits at code `84` after the prepared
PostgreSQL attempt commit and before Node contact. A replacement Worker
process resumes the same attempt and completes one `message_only` Inbox. The
Temporal run ID, Workflow memo identity, PG provider reference and Node
receipt are separately verified. The two Worker process identities and their
exit/readback states are kept in owner-only private evidence. No native Driver
call is claimed for these `message_only` restart scenarios.

`P1-LEASE-FENCING` derives its execution owner from the same WorkItem and
actual Node machine/boot as its delivered message. The Node Machine ID is the
Gate runner's observed Machine ID, and PG attempt selection, Node SQLite,
signed enrollment and every result are compared against it. Signed Domain
APIs register the original Runtime/Attempt. A real PostgreSQL Lease fences
the first `LocalFileEffectGateway` write. After its release, a separately
granted producer obtains a second signed Runtime/Attempt and the same resource
at generation 2. The replacement owner writes new bytes and an independent `effect.read`
principal verifies them before the original owner attempts a late write using
its original Grant, Runtime, Attempt and fencing token. The late call must
raise `FencingRejected`; file SHA/identity, all effect markers and both
PostgreSQL Lease identities must remain byte-equivalent across that call.
After generation 2 is released, the independent reader verifies the same
intent, completion and current file again, while the original completed
marker history remains pinned. Readback binds both owners,
both Lease generations and acquire/release journals to the Delivery message,
Node journal, effect inode/content and auxiliary Temporal workflow. Fencing
tokens remain in owner-only Gateway/PG state; probe results contain only their
digests. This is a local file effect, not a native model-produced artifact or
an acceptance decision.

`P1-UNCERTAIN-EFFECT` uses the delivered message's WorkItem and DeliveryAttempt
ID for a signed Node execution Attempt. A real CAS output, signed execution
receipt, independent Review and ready revision establish the Domain's candidate
binding before its PostgreSQL Lease. The file Gateway is interrupted after the
target replacement and fsync but before its completion marker. A real
`effect.register` observes the prepared marker and stores `uncertain`. Only the
original operation is resumed from readback; a counted target replacement must
remain exactly one. `effect.reconcile` then observes the completed original
marker, with exact command replay, an independent historical reader and late
old-owner fence. Every Gate layer checks the same message, Attempt, Lease,
effect operation, Node Machine and source identity. This is a local file effect
and uses no model call.

`P1-STALE-BASELINE` starts from the delivered message's WorkItem and
DeliveryAttempt ID. A signed Node execution receipt, real CAS output/readback,
independent Review and ready revision bind the actual source commit. The
prepared CAS output is first invalidated and the real finalizer rejects
acceptance without leaving command rows; the original bytes are restored.
An owner-private temporary Git checkout is copied from the Gate source
snapshot. Its first commit must have exactly the Gate source tree; a second
commit changes one tracked file and records its HEAD, tree, parent and raw
diff. Driver and OS layers independently recreate both commits from the fixed
source snapshot and verify the same identities. A scoped
PostgreSQL fault then sets the WorkItem's authoritative source baseline to
that actual second commit while the signed Attempt, receipt and ready snapshot
retain the original baseline. The real finalizer's acceptance command and exact retry both
reject; no AcceptedStateRevision, denial command ledger row or protected Effect is
committed. PG, Node SQLite, auxiliary Temporal, CAS and OS source readback
compare the stale baseline to the same message/Attempt/source lineage. The
baseline change is explicit test fault injection; no Runtime baseline-update
command or mutation of the Gate's fixed source checkout is claimed. The second
Git commit exists in owner-private temporary storage while being verified;
the Gate output keeps only the source identities and safe one-file diff.

`P1-PARTIAL-ARTIFACT` interrupts the production CAS publisher after a short
temporary-file write and injects `EIO` before a complete ArtifactRef exists.
It checks temporary-file removal and directory fsync, an independent readback
of a complete control artifact, and absence of the partial output. A signed
receipt referencing the missing output is rejected by the Domain, and the
Finalizer cannot reach readiness or acceptance. The same delivered message,
Attempt, Node Machine, PostgreSQL state and auxiliary Temporal identity are
read back across six Gate layers. The fault hook is confined to the probe
process; no native model-produced artifact is claimed.

`P1-HARNESS-REPLACEMENT` uses one committed Delivery Attempt and a versioned
HarnessSessionBinding. The old Session result is retained as `fenced_late`;
the replacement Session's structured terminal result is written to CAS,
recorded by the Node response Outbox, projected to PostgreSQL exactly once and
read back through all six Gate layers. This no-model scenario verifies identity
and recovery semantics without claiming a native model lifecycle.

`P1-NATIVE-MULTIAGENT-OFF` remains `NOT_RUN`. Its isolated component adapter
starts pinned Codex 0.153.2 and OpenCode 1.18.30 under private Systemd user
units without issuing a model request. Codex effective feature pages must show
both native multi-agent flags disabled under the active permission profile.
OpenCode effective `/config`, `/agent` and `/experimental/tool/ids` readbacks
must retain the selected deny-all Agent and a bounded tool inventory. The
HostNode request schemas expose no delegation override, and the current
PostgreSQL AgentSlot and Scope Policy fences reject a changed launch before a
new attempt or process. These are configuration and no-model boundary facts:
Codex does not expose a complete effective tool list at this stage, and an
actual model request's refusal to delegate has not been measured. The adapter
therefore cannot make the formal scene available.

The `p1-loopback-provider` profile is Linux-only. It uses the host network and
admits only `127.0.0.1:54329` PostgreSQL and `127.0.0.1:7239` Temporal. Host
network sharing is recorded as such; it is not described as a private network.
The profile directory must be owned by the executing UID with mode `0700`, and
the JSON file must be one regular `0600` link opened with `O_NOFOLLOW`. The DSN
may exist only in this file. Plans, argv, environment evidence, raw test output
and emitted probe results are scanned so the password does not leave the
profile boundary.

The Codex strict Driver uses a separate no-network helper profile. Neither
model lifecycle scenario is admitted by a historical receipt.
`P1-CODEX-LIFECYCLE` and `P1-OPENCODE-LIFECYCLE` remain `NOT_RUN` until their
owner-pinned same-run host scenes, one-request decisions, terminal readbacks
and process-tree postflights are executed and reviewed. Integrated acceptance
requires both completed lifecycle records in that same authenticated Gate run.

The Gate runner's `runtime_profile` provisions a digest-pinned, read-only
profile at `/run/acs-p1/profile.json` and a reviewed Runtime Python environment
at the profile's `sandbox_python` path. The host runner verifies the user-bus
peer and mounts a digest-bound read-only OS attestation; the bus socket stays
outside the sandbox. The formal source, Gate tree,
run root and HMAC key remain hidden. No DSN value is copied into source, plan,
argv or ordinary environment. A runnable Gate still needs an independently
reviewed plan and real run on the target Machine; this harness's isolated
tests do not promote a Gate.

`p1_profile_plan.py` emits six commands only for the eleven implemented scenarios
when their required real resources are current, and an empty command list for
every gap. Missing command kinds therefore stay `NOT_RUN`; the harness never
fabricates a passed result. The command and six readbacks must share one
message, operation, attempt/receipt and source lineage. PostgreSQL readback
rechecks canonical hashes, operation/outbox state, attempt history, receipts,
Grant and Inbox state. A changed authoritative row is rejected.
After private evidence is captured, `p1_profile_probe.py cleanup` drops only the
dedicated probe schemas. Gate execution and cleanup must remain outside the
formal checkout.
