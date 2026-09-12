# P1 Codex host Node entry candidate

This candidate moves the privileged process lifecycle outside the Gate probe. A
host process owns `DomainAuthority`, `DeliveryDispatcher`, `LocalNodeEndpoint`,
`NativeDeliveryAdapter`, `CodexAppServerDriver`, and `SystemdUserSupervisor`.
The sandbox sees one run-specific Unix socket. Its fixed request schema has only
`dispatch` and `readback`; it has no executable, argv, environment, unit, PID,
credential, or generic host-command field.

The host pins run ID, tenant, Authority incarnation, Scope, AgentSlot, exact
Scope Policy digest, endpoint, source commit, native executable digest, config
digest, and deadline. Before dispatch it compares those pins with
the already committed PostgreSQL message, command correlation ID, activation,
source baseline, database clock, and owner-controlled artifact files. A private
SQLite ledger binds the run to one command/message/operation and one immutable
policy digest before native work. `DeliveryDispatcher` then owns the actual
PostgreSQL attempt, current Grant checks, marker, Node SQLite commit, native
boundary, and replay behavior. The guest cannot create or choose an attempt.

`start_native` and `stop_native` are host-callable methods, absent from the
socket schema. Start requires the exact committed dispatch identity and reuses
the Domain's current `message.send` and `runtime.invoke` Grant checks. The host
also locks and checks the WorkItem, active AgentSlot, active Scope and pinned
Policy digest under the same PostgreSQL transaction held through Systemd spawn.
After observing the unit, it checks the database clock against the earliest
Grant, command, message, operation and run deadlines before recording success;
late starts are stopped and remain uncertain. It persists a boot intent before spawning, and observes a
run-labelled Systemd unit with birth and cgroup identity. A repeated start or
an intent left by a crash is rejected. Stop checks the stored unit/birth identity
before terminating, and requires an empty cgroup proof. Readback may continue
after the dispatch deadline and after native artifacts have been cleaned up.

The isolated no-model tests use a fixture Driver as the downstream native
boundary. They exercise actual PostgreSQL, Node SQLite, the dedicated bubblewrap
helper, a guest with only the fixed socket mounted, and a real host user-manager
Systemd service. The bwrap guest positively checks that its `/run/user/.../bus`
and the formal `/home` checkout are absent. The host service observes and stops
its unit; the test proves an empty cgroup and no EnvironmentFile residue.
An additional test uses the production `CodexAppServerDriver` and
`NativeDeliveryAdapter` under Systemd with an executable Codex-shaped JSON-RPC
fixture. It exercises native `turn/start` once, driver journal readback, and
the host's immutable bootstrap/termination path without a provider call.
The tests also cover same-operation replay, a competing operation in one run,
two host instances, ACK loss, a prepare interruption, post-marker uncertainty,
Grant revocation, changed digests/artifact mode, malformed socket requests,
restart policy drift, and deadline-bounded dispatch with later readback.
Post-send permission removal, Scope/Authority/AgentSlot revocation, and Policy
change each reject before a Systemd launch or Node effect.

The actual Codex binary/config and provider were **not** used by these tests;
no model turn was sent. The complete P1 Gate, Temporal route, terminal response
projection, real Codex binary bootstrap, external budget authorization, and
host postflight after a killed host process remain **NOT_RUN**. In particular,
if the host dies after Systemd accepts a unit but before it retains the owned
handle, the owner runner must independently find and quarantine the run-labelled
unit. The ledger leaves boot state `intent` and never authorizes another spawn.

Integration must construct the host objects from a reviewed owner-only profile,
keep the user bus outside the sandbox, mount only this socket, and stop or
quarantine the run's unit in host-side `finally` and postflight. This candidate
does not change a formal Gate result.
