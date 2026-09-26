# P1 real-resource probe profile

This harness prepares executable evidence commands for the 18 P1 scenarios.
It does not write a formal Gate. Five scenarios currently have an actual
fixed-identity Runtime lineage adapter: `P1-DOMAIN-TRANSACTION`,
`P1-AUTH-REVOCATION`, `P1-COMMAND-DEDUP`, and `P1-INBOX-ACK-LOSS`.
`P1-CORE-RESTART` is the fifth adapter. The other 13 have no runnable command
and remain `NOT_RUN`.

Each runnable scenario commits its own command, operation, event, Outbox,
message and receipt lineage in a dedicated PostgreSQL schema. It records
Node and Driver observations in a private SQLite journal, starts a distinct
Temporal workflow whose ID is the delivery operation plus `:temporal`, and
emits six separately read-back probe results. The Temporal workflow is an
auxiliary recovery observation of the same scenario identity; it is not a
claim that the Delivery dispatcher was itself invoked by Temporal.

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

The `p1-loopback-provider` profile is Linux-only. It uses the host network and
admits only `127.0.0.1:54329` PostgreSQL and `127.0.0.1:7239` Temporal. Host
network sharing is recorded as such; it is not described as a private network.
The profile directory must be owned by the executing UID with mode `0700`, and
the JSON file must be one regular `0600` link opened with `O_NOFOLLOW`. The DSN
may exist only in this file. Plans, argv, environment evidence, raw test output
and emitted probe results are scanned so the password does not leave the
profile boundary.

The Codex strict Driver uses a separate no-network helper profile. No Codex
model/login evidence is currently admitted, so `P1-CODEX-LIFECYCLE` remains
`NOT_RUN`. OpenCode model evidence must say `pass`, bind the current source
commit, contain exactly one prompt and prove process-tree cleanup; stale
evidence is not admitted. Integrated acceptance remains `NOT_RUN` until both
model lifecycle scenarios are complete.

The Gate runner's `runtime_profile` provisions a digest-pinned, read-only
profile at `/run/acs-p1/profile.json` and a reviewed Runtime Python environment
at the profile's `sandbox_python` path. It mounts only the verified user-bus
socket needed for `systemctl --user` readback. The formal source, Gate tree,
run root and HMAC key remain hidden. No DSN value is copied into source, plan,
argv or ordinary environment. A runnable Gate still needs an independently
reviewed plan and real run on the target Machine; this harness's isolated
tests do not promote a Gate.

`p1_profile_plan.py` emits six commands only for the five implemented scenarios
when their required real resources are current, and an empty command list for
every gap. Missing command kinds therefore stay `NOT_RUN`; the harness never
fabricates a passed result. The command and six readbacks must share one
message, operation, attempt/receipt and source lineage. PostgreSQL readback
rechecks canonical hashes, operation/outbox state, attempt history, receipts,
Grant and Inbox state. A changed authoritative row is rejected.
After private evidence is captured, `p1_profile_probe.py cleanup` drops only the
dedicated probe schemas. Gate execution and cleanup must remain outside the
formal checkout.
