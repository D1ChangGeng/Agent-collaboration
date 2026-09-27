# P1 OpenCode lifecycle scene

The candidate binds one committed `message.send` command to the existing
Domain delivery attempt, a Temporal Workflow/Run, a Node SQLite invocation,
one OpenCode `prompt_async`, a correlated assistant message, the Node response
Outbox, a PostgreSQL `response_received` projection, and a stopped Systemd
unit. The host accepts only fixed `dispatch` and `readback` socket requests.
The protected spawn path rechecks current Grant, Scope, Policy, AgentSlot and
deadline before creating the native process.

OpenCode 1.18.30 was observed on Linux with binary SHA-256
`87bd160e053af86b5b409daabf71f8dc05bbc3a2a3a5f563f36011cdf706a999`.
The actual `/doc` response was captured without a model request as
`runtime_tests/schema-1.18.30/opencode-openapi.json`, SHA-256
`cf12e9739510a196c7f25eb938555cfb66d901957f66f840a12d4489ae440ac3`.
The generated effective agent has deny-all permissions followed by a native
`external_directory allow` for its private `data/opencode/tool-output/*`
directory. The Driver now accepts only that pattern and private
`tmp/opencode/*`, under owner-0700 roots with realpath and no-symlink checks.
Any other allow or ask after the final deny-all is rejected.

The separate owner-0600 scene and budget admission binds the actual source
commit/tree, run/Machine/Node, provider/model identifiers, native/config/schema
digests, one `prompt_async`, at most six read-only terminal collections, and a
120-second deadline. It checks the provider key-file inode with `O_PATH` and
does not read its bytes. The provider route and any credential remain in
owner-only input, outside tracked source and review evidence.

The no-model integration fixture exercised one synthetic HTTP terminal under
real Systemd, PostgreSQL and Temporal. The original response was stored in
CAS, recorded by Node, projected by Domain, and independently read back from
all six layers. Grant permission reduction, Scope Policy change and AgentSlot
revocation each prevented spawn and attempt creation. Later changes to the
Node mailbox command or PostgreSQL selection Machine were rejected by fresh
readback. The fixture is engineering evidence, not a model or Gate result.

The P1 scenario remains `NOT_RUN` until a trusted host runner mounts the
owner-pinned scene and decision, dispatches one real model request, and records
the same-run six-kind evidence with postflight. No decision file has been
issued for this candidate. `P1-INTEGRATED-ACCEPTANCE` must require both Codex
and OpenCode lifecycle scenario records from the **same HMAC-authenticated
run**, with matching source commit/tree, Machine/Node and verified host
postflights. Historical model receipts cannot satisfy that dependency.
