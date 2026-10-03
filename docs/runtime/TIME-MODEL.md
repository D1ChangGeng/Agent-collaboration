# Runtime time model

ACS uses four time layers with distinct responsibilities. Authorization follows
one trusted Authority reference; local duration and display rules preserve that
reference's meaning across machines and timezones.

| Layer | Value and owner | Use |
| --- | --- | --- |
| Canonical facts | Aware UTC instants with source provenance; the Domain reads PostgreSQL time | Commands, Grants, evidence, durable deadlines and event facts |
| Local duration | Monotonic time in the current process | RPC budgets, live execution leases, idle TTL and bounded waits |
| Connection time | A calibrated UTC interval bound to the authenticated Authority and endpoint | Sender, receiver and native admission, freshness and conservative remaining time |
| Presentation | An available IANA timezone selected by the client surface | Display values alongside canonical data |

## Authority and connection binding

`DomainAuthority.canonical_now(cursor)` reads fresh PostgreSQL
`clock_timestamp()` and normalizes the aware result to UTC. Authorization reads
it before validation and again after locks. Domain Lease expiry remains a
canonical `TIMESTAMPTZ` deadline, checked against fresh database time.

MCP transport `metadata.observed_at` records node-local UTC, labeled
`timestamp_source: node_local_utc` and `timestamp_authority: unverified`.
Treat it as transport observability. Admission and freshness use the trusted
Authority provider and Authority facts carried in the result data.

`ConnectionClock.from_authority(...)` obtains its reference through the
existing authenticated Authority database connection. An admission timestamp is
input checked against this reference. Production injects the bound provider
through sender, receiver callbacks, native Driver, journal and delivery adapter.
The clock remains outside the serialized `AuthorizedOperation` fields.

`now()` is the calibrated interval's midpoint estimate, used with its bounds
for deadline and freshness decisions. New journal events, native receipts and
terminal observations use `observation_time()`: a fresh authenticated calibration
returns the original Authority UTC sample `T`. This fact stamp follows the
observed action and is checked against the Authority's current time. Re-reading
a cached terminal result preserves its original timestamp and payload/hash.
Clock audit snapshots retain the estimate and bounds with their provenance.

The binding carries Authority ID/incarnation, tenant and Scope, Connection,
Endpoint/revision, Runtime/revision, Machine, Node/binding revision, boot,
AgentSlot and receiver journal generation. The process identity is also checked
when reading monotonic time. Private and Tunnel connections require that full
binding. Local clock helpers serve isolated loopback and unit fixtures;
production native deployments use the Authority provider.

Process, boot, Authority, Connection or registered binding replacement requires
a fresh provider and calibration. Persisted audit snapshots describe previous
samples; restart recovery derives a new live anchor for the current identity.

## Calibration and uncertainty

The client measures monotonic send and receive instants around the authenticated
reference call. The Authority's UTC sample is placed at the round-trip midpoint.
For send/receive values `m0`, `m1`, Authority sample `T`, and current monotonic
value `m`, the estimate is:

```text
RTT = m1 - m0
midpoint = (m0 + m1) / 2
estimated UTC = T + (m - midpoint)
progression gap = abs(wall elapsed - monotonic elapsed)
uncertainty = RTT / 2 + resolution + age * drift_ppm / 1_000_000 + progression gap
earliest UTC = estimated UTC - uncertainty
latest UTC = estimated UTC + uncertainty
```

Age is elapsed monotonic time since receiving the sample. Linux uses
suspend-inclusive `CLOCK_BOOTTIME` by default; other environments use the
available local monotonic clock. The local wall clock contributes a diagnostic
offset; monotonic elapsed time advances the estimate.
Wall/monotonic progression differences add a separate uncertainty radius,
including after suspend/resume on a clock that excludes suspension. The RTT
radius already accounts for sample position; progression gaps consume additional
uncertainty. Excessive uncertainty or overlap with expiry requests a fresh
Authority sample. Wall observations supply the liveness signal; the estimate's
centre advances from the authenticated reference and monotonic elapsed time.
Local duration measurement stays monotonic. Defaults bound sample age to
30 seconds, RTT to 2 seconds and uncertainty to 1 second, with 100 ppm aging
drift and one microsecond resolution.

A sample exceeding age or uncertainty bounds refreshes through the Authority reference.
An offline reference or a fresh sample still exceeding RTT/uncertainty bounds
makes the clock unavailable. Changed process identity or a backwards monotonic
reading invalidates its live clock domain. Unavailable time stops protected
admission until a valid bound is established.
The model aligns consumers with this Authority within measured bounds. The
operator remains responsible for the reference clock's stability. An Authority
wall backstep is a clock incident requiring reference inspection, recalibration
and review of affected admissions and evidence.

## Deadlines, leases and readiness

`require_before(deadline)` requires `latest_utc < deadline`. An overlapping
interval triggers a fresh sample. A refreshed interval wholly past expiry
raises `ClockExpired`; overlap still present raises `ClockUncertain`. Both are
unavailable authorization time. Uncertainty reduces the usable window; the
Grant and canonical deadline retain their original expiry.

`remaining(deadline)` derives the conservative duration from the deadline and
upper UTC bound. Local timeouts and live leases use a process-local monotonic
end derived from that duration. Durable lease state retains its canonical
expiry, ownership and fencing identity. Raw monotonic values stay in process
memory; a restart reconstructs admission from durable Authority state.

Native idle readiness lasts at most two seconds and carries calibrated UTC
`observed_at`/`expires_at`, a generation and clock audit snapshot. Producer UTC
expiry uses its earliest UTC bound before inspection plus the two-second
lifetime, capped by the operation deadline. After native inspection, a fresh
Authority sample supplies `observed_at`. Inspection and calibration consume the
same window, including producer uncertainty; an exhausted window defers queued
work. The native adapter holds its live expiry in monotonic memory and verifies the generation,
clock calibration and UTC freshness before use. The remote receiver signs its
readiness observation; the sender applies the same bound against its trusted
connection clock. Busy, unknown, stale or unavailable readiness defers queued
work before the dispatch marker. After dispatch, an uncertain outcome requires
readback of the same invocation.

## Wire compatibility and replay

Existing aware, offset-bearing wire v1/v2 inputs retain their signature and
hash canonicalization. New authored instants use UTC. Naive absolute timestamps
are rejected; the native response collector requires an explicit timezone and
normalizes its observation to UTC while preserving the signed/result payload.

Clock IDs, sample IDs and sample sequence describe calibration provenance.
Command ordering follows Domain revisions and durable command/event identity.
Receiver replay protection uses signatures, durable request/message/command IDs,
nonce uniqueness, boot/journal generation and the one-consumption dispatch
fence. Calibration sequence is an audit counter within its process.

Snapshots record canonical/earliest/latest UTC, reference and binding identity,
clock/sample IDs, sequence, offset, RTT, uncertainty and age. They carry audit
facts suitable for later inspection; live monotonic ownership belongs to the
current process.

## Presentation

`SurfaceSettings` and `ProjectHttpSettings` accept `presentation_timezone`, an
available IANA timezone such as `Asia/Tokyo`, with `UTC` as the default. MCP
results expose display data under `metadata.presentation.timezone` and
`metadata.presentation.timestamps`. Timestamp entries identify their canonical
UTC value, timezone, formatted display and daylight-saving `fold`; their keys
are JSON Pointer paths into the returned data and observation metadata,
including `/metadata/observed_at`.

This sidecar leaves canonical result data, signed payloads, hashes and ordering
intact. A timestamp that cannot be rendered in the selected zone is omitted
from the bounded presentation sidecar while its canonical result remains
available. Timezone and daylight-saving changes affect display; authorization
continues to use canonical Authority time.

## Implementation and evidence scope

The mechanisms are in [connection_clock.py](../../runtime/connection_clock.py),
[DomainAuthority](../../runtime/domain.py),
[receiver clock binding](../../runtime/receiver_config.py),
[native delivery](../../runtime/native_delivery.py) and
[MCP presentation](../../runtime/mcp_runtime.py).

Regression coverage includes [calibration](../../runtime_tests/test_connection_clock.py),
[Authority SQL time](../../runtime_tests/test_authority_clock.py),
[receiver admission](../../runtime_tests/test_receiver_connection_clock.py),
[native synthetic transports](../../runtime_tests/test_native_connection_clock.py)
and [presentation](../../runtime_tests/test_time_presentation.py).
[Recovery PostgreSQL checks](../../runtime_tests/test_recovery_postgres.py)
cover the Human Bridge expiry boundary with fresh Authority time after locks.
Node response Outbox retries return to current Domain authorization; native
fact tests check fresh sample stamps and cached terminal preservation under
asymmetric RTT. These checks establish their measured component and fixture scopes. The
control proof can use calibrated Authority time with a durable consumption
marker; earlier skew-based control validation remains available for historical
fixtures.
Real Harness, ordered Gate and cross-machine conclusions retain the exact source,
host, Profile and readback evidence of the run that established them. A timing
change requires fresh affected evidence under the
[Runtime adoption contract](UPGRADE-CONTRACT.md).
