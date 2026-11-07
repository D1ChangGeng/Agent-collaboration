# Committed event-intent foundation

This increment supplies PostgreSQL event storage, ordered publication, immutable
metadata snapshots and opt-in SSE. `communication_event_stream` defaults off in
Surface and HTTP settings. HTTP enablement also requires `communication_client_api`.
Explicit operator initialization adopts the event and snapshot schemas; startup
verifies them and never performs that adoption. The current communication-feature
producers are implemented. These producers and local tests alone do not establish
WP06 completion or the package's cross-host/Harness/model qualifications.

Source transactions persist an immutable event intent beside their existing
message/reply/delivery/private-state write. Intents contain references, revisions
and minimal internal ACL metadata; they contain neither message nor draft text.
The publisher selects only committed intents, locks the project stream counter
first, and atomically appends the stream row plus its published marker. Source
writers never acquire that counter lock.

This separates source allocation from publication order. A transaction that
allocated a lower intent ID but committed late receives a later stream sequence.
An RR snapshot of authoritative data and published high water cannot lose that
late transaction. A source already represented in the data snapshot but still
unpublished may subsequently replay; consumers must deduplicate event IDs and
respect the corresponding projection's resource revision.

Automatic hooks cover `message.committed`, explicit `reply.linked`,
`delivery.changed`, `read_state.changed`, `draft.changed`, viewer-specific
`conversation.updated` (including preferences), and `notice.created/updated`.
Message revision is the explicit reply-relation revision; delivery has its separate
transactional version. Conversation and Notice DTOs now use serialized per-viewer
projection rows, rather than competing sums of independently committed counters.
Their getters fence the version before reading source cells; writers acquire the
counter after the source mutation. Same-principal Slots keep distinct private views.

Receiver metadata is persisted only after actual endpoint/epoch/host revalidation.
Its resource revision survives binding/generation changes and differs from
`binding_epoch`. Full metadata refreshes advance it, while semantic digests suppress
GET → event → GET loops caused only by proof/time renewal or entry reordering.
Actual state changes produce `receiver.observed`; changed capability/configuration
also produces `capability.changed`. Stale or corrupt reads return explicit unknown
and cannot reuse the previous Native session. No provider I/O occurs under SQL locks.
The optional attachment source records owner-only `attachment.ready` intents
alongside ready publication and pin revision changes. The intent carries the
opaque resource ID/version, actual viewer/address/Scope and an empty payload.
Names, MIME, hashes and bytes are not copied. Its explicit adoption requires both
attachment and event schemas; existing ready objects are not backfilled as new
ready facts. Current owner metadata visibility and feature availability are
rechecked before emitting. Recipients hydrate accepted references from their
actual `message.committed` event and message read, rather than inheriting private
upload notifications. Native-link producer hooks remain WP07 work.

The source boundaries are explicit:

| Event family | Source of the resource revision |
|---|---|
| `message.committed`, `reply.linked` | Immutable message insertion and the original message's explicit reply relation |
| `delivery.changed` | Transactional delivery version advanced by state, binding, attempts and receipts |
| `read_state.changed`, `draft.changed` | The actual viewer-owned private row revision |
| `conversation.updated` | Directed viewer projection updated by message and that viewer's read/preferences sources |
| `notice.created`, `notice.updated` | Recipient/principal projection combining notice technical source with its own seen state |
| `receiver.observed`, `capability.changed` | Validated persisted receiver observation revision and semantic/capability digests |

`communication_projection_event_schema.sql` installs the conversation/notice
projection hooks. Receiver observation writes record their corresponding intent
inside the caller-owned transaction and savepoint. Neither registry presence nor
an endpoint's active status becomes a positive Native observation. Control kinds
such as `permission.changed`, `resync.required` and `stream.end` invalidate or end
the transport; they do not manufacture domain facts. Native-link kinds have no
producer until that service is implemented.

`adopt_event_storage(connection)` is an explicit operator transaction following
client-storage adoption. Startup verifies an already adopted event schema and
does no DDL or repair. Adoption creates no invented historical events. Existing
data is represented by the snapshot, while future committed source writes produce
intents. `publish_event_intents` requires the caller's short transaction. Bounded
local maintenance publishes committed intents, expires stream prefixes and prunes
only expired snapshot caches, including when delivery uses an external worker.
Projection maintenance does not claim an internal Native dispatcher is active.

The event-enabled initialization order adopts the existing client/viewer/notice
stores, conversation and notice viewer counters, receiver observation storage,
event storage, projection event hooks, then snapshot storage. Each optional schema
is independently verified at startup, including when its state already exists
after a feature flag has been disabled. Legacy row reconciliation seeds actual
projection baselines; it does not label adoption time as a historical notice or
invent old `notice.created` events.

The internal replay reader requires a trusted service cursor and grants no
authorization. The facade checks current Profile, OAuth, Grant and all effective
family bindings on each batch. Immediately before yielding a queued event it
looks up that immutable intent and checks current participant/recipient/object
Scope visibility again, even when the caller's own authorization hash is unchanged.
No database transaction remains open across a network yield. Public cursors use
compact namespace/filter digests, fit the wire bounds for legal Unicode identities,
and bind actual actor and current authorization.

`GET /snapshot` pre-observes receivers outside SQL, then captures all metadata
families and the published high water in one short RR view. The observation budget
is one returned page; unmeasured receivers remain explicitly unknown. The service
materializes frozen metadata DTOs for up to 300 seconds, commits, then rechecks
fresh authorization and current object visibility. Pagination returns those exact
DTOs, never refreshed receiver axes or current names/preferences. Snapshot quotas
reject atomically rather than silently truncate; expired caches do not delete
messages, drafts or operation history. `notice_count` means the caller's unseen
system notices at the cut.

The snapshot's unfiltered anchor can establish a selected event-kind stream;
subsequent emitted cursors bind that exact filter. `after_cursor` and
`Last-Event-ID` must agree. The HTTP route requires a snapshot/saved cursor and
never starts silently at the latest position. SSE holds at most 256 queued events
or one MiB of encoded data, monitors authorization while backpressured, and closes
a stalled consumer with a minimal resnapshot control using the last yielded cursor.
Heartbeat comments have no domain effect. Producer and queue resources end on disconnect.

The headless SDK in `sdk/communication-state.ts` and `communication-stream.ts`
deduplicates bounded event IDs, treats message/delivery/private projection versions
independently, preserves local drafts and pending commands across resets, and
never automatically reconnects, resends or synthesizes an Agent reply. A new
authorized snapshot is required after an authentication/gap/reset control.
Local work remains tagged to its stable viewer. Switching Slots or principals
archives the prior viewer's work rather than exposing it under the new Actor;
unowned work requires an explicit claim and bounded archives never evict it
silently. An acknowledged noncomparable refresh at the same DTO revision installs
the newly authorized value, rather than marking the previous capabilities fresh.

The real local consumer episode is implemented by
`runtime_tests/test_communication_headless_live.py` and
`sdk/tests/communication-live-consumer.mjs`. A separate Node process uses real
`fetch` against an owned loopback Uvicorn listener, the mounted OAuth resource
server, isolated PostgreSQL and the actual SDK reducer/stream parser. The episode
checks matching `after_cursor`/`Last-Event-ID` across reconnects, duplicate replay,
authorized UTF-8 body continuation with digest verification, one send and one
explicit authenticated peer reply command, private read/preferences/draft/seen
writes, and cache invalidation after actual Grant revocation. The local unsent
draft and exact pending command remain attached to their viewer, with no resend
or Native input. Owned consumer/server processes are closed after the episode.
The issuer and Native drivers remain controlled fixtures. This exercises the local
HTTP/SSE integration boundary; it is not installed-host, production, cross-host or
real-model qualification. This episode alone does not qualify the full regression
or establish WP06 completion.

Publication retries cannot duplicate an intent. Retention deletes only a
contiguous expired stream prefix and retains the source-key tombstones and
published markers; messages, operations and request receipts are not cleaned up.
Replay behind the recorded floor raises `EventCursorExpired`, mapped by the
HTTP layer to 410/resnapshot rather than the latest position. An absent
clock with `after=0` immediately returns an empty batch, linearized at that lookup;
it never queries a later stream view that may have been partially purged.

`committed_at` is the source timestamp recorded inside the transaction whose
commit made the fact visible, not a separately measured physical commit instant.
`published_at` belongs to ordered publication. Neither orders an external Native
journal or proves model consumption or an Agent reply.
