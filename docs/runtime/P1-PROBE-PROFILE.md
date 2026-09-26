# P1 real-resource probe profile

This candidate prepares executable evidence commands for the 18 P1 scenarios.
It does not write a formal Gate. Each runnable scenario executes its selected
Runtime integration tests once, records a private SQLite ledger and a dedicated
PostgreSQL schema, submits and reads back an actual Temporal marker, then emits
separate PostgreSQL, SQLite, Temporal, Driver and OS observations using the P1
probe-result schema.

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

Gate runner integration is intentionally pending its next revision. That runner
must digest-pin and read-only bind the owner-only profile file at
`/run/acs-p1/profile.json`, plus a reviewed Runtime Python environment at the
profile's `sandbox_python` path. The formal source, Gate tree, run root and HMAC
key remain hidden. No DSN value may be copied into source, plan, argv or ordinary
environment. The current runner lacks these two allowlisted binds, so this
candidate does not claim a runnable Gate plan yet.

`p1_profile_plan.py` emits six commands for every scenario whose required real
resources are current and an empty command list for every gap. Missing command
kinds therefore stay `NOT_RUN`; the harness never fabricates a passed result.
After private evidence is captured, `p1_profile_probe.py cleanup` drops only the
dedicated probe schemas. Gate execution and cleanup must remain outside the
formal checkout.
