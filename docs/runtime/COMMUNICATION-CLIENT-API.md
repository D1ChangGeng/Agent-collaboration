# Communication HTTP client increment

The opt-in `/api/communication/v1` facade shares the existing PostgreSQL
Authority, ProjectService authorization, natural-message ledger, explicit reply
index, dispatch and OAuth subject/client bindings. It is a local development
increment. Delivery scope follows the v1.1.0 revision: Core P0 and Client P1 are
assessed separately; implemented optional P2 features are retained. Ordered
events, frozen snapshots, NativeLink metadata and the receiver-action HTTP facade
are implemented locally. Current qualification and remaining gaps are recorded in
[the adoption state](../../integration_evidence/acs-stage-agnostic-20261106/adoption-state.json).

## Enable and adopt

`communication_client_api` defaults to `false` in both `SurfaceSettings` and
`ProjectHttpSettings`. The Surface setting selects the optional storage during
the existing explicit operator `ProjectService.initialize()` adoption step:
client projections, viewer-ownership decisions/fences, then notice projections.
The HTTP setting mounts the facade alongside the existing `/mcp` resource.
Its OAuth audience and operator-established bindings are the same resource
configuration; HTTP request bodies never select a principal, Grant or Slot.

Normal startup verifies the optional schema and never creates tables, cursor
keys, identities or Grants. Enabled HTTP startup fails until adoption completes.
After adoption, startup continues checking this storage even when the HTTP
feature is disabled because its source-transaction version triggers remain.
Disable the HTTP flag to withdraw the facade; preserve its tables, drafts,
idempotency receipts and cursor key. No production adoption has been performed.

`communication_event_stream` also defaults to `false` in Surface and HTTP settings.
Its HTTP routes require the client API flag. With the event flag selected, explicit
initialization additionally adopts directed conversation versions, notice viewer
versions, receiver observations, event intents/ordered publication, projection
producers and frozen snapshot storage. These schemas keep their own identities and
checksums. Disabling the flag does not remove their persisted state or turn a
damaged adopted schema into an automatic repair.

## Implemented routes

The facade provides public version metadata, authenticated profile, projects,
Routes, contacts, natural-message history and UTF-8 continuation, literal
case-sensitive search, send, wait, delivery facts and original-operation queries.
It also provides direct-pair conversation resolution/list/detail, receiver and
system-notice queries, explicit notice seen state, and private read-state,
preferences and draft GET/PUT; draft DELETE retains a versioned tombstone.

Personal-state writes require a stable `Idempotency-Key` and quoted revision such as
`If-Match: "0"`. Permission checks precede receipt lookup. Exact retries return
the original outcome before a stale revision is checked; changed intent under
the same key conflicts. Separate resources have separate CAS versions. A read
frontier names a visible message in the actual pair and stores the pair-local
sequence, rather than exposing the global message index. Read, list, resolve and
draft operations perform no Native activation or message consumption.

An empty pair view is derived from an authorized stable contact and can hold a
draft before its first message. No create-conversation Domain step is required.
The global Actor address is the authenticated principal; routable self addresses
are project-scoped and appear in contacts and message authors.

Private conversation state uses a stable viewer key containing the actual
trusted communication address and principal. Two Slots sharing a principal
remain separate even when they are each other's conversation peer. State survives
credential/Grant/incarnation renewal. Write-key namespaces additionally contain
Authority incarnation, project, address and operation kind. Legacy experimental
principal-only rows are retained and require an explicit ownership decision;
they are never silently shown to both Slots or replaced by empty state.

`adopt_viewer_storage` installs the decision/fence schema only.
`adopt_legacy_personal_state` is a trusted operator-cursor helper, not a public
management endpoint. After selecting a proven viewer it copies exact state,
revision and timestamps while retaining original rows and old receipts. Replays
cannot overwrite later viewer edits. Disable the older HTTP feature before this
step; its unpatched reader is not repaired by a writer fence. Keep legacy receipt
history and reconcile pending private edits against the chosen view.

Receiver queries preserve the existing evidence flag. Disabled evidence yields
actual binding metadata and unknown axes with no provider call. Enabled evidence
is read outside database transactions and revalidated for binding, authorization
and TTL afterward. When observation storage is adopted, the resulting shared
metadata is persisted under its actual endpoint/epoch/host selection. Its durable
resource revision is distinct from the binding epoch and survives generation or
epoch changes. Proof/time renewal can refresh the stored DTO without generating
another semantic invalidation. These reads perform no lifecycle actions.

System notices are recipient-scoped operational facts. Their own Native receipt
comes only from the separate notice-delivery ledger, never from the original
message's ACK. Seen is explicit private state. New HTTP notice handles use stable
persisted random IDs; old MCP/global-sequence references remain accepted as input
aliases, while public outputs and encrypted cursors expose no global ordinal.
Legacy notices have an unknown creation timestamp; new inserts record it in the
source transaction. Missing failed-endpoint provenance remains null.

HTTP accepts 256 KiB UTF-8 message content by default, with a 2 MiB JSON framing
limit and a bounded trusted packet budget including JSON escaping. The existing
MCP content/packet limits remain. With attachments disabled, metadata advertises
attachment_count/aggregate/staging capacity as zero; attachment_bytes=1 is the
schema's positive sentinel. Enabled attachment limits come from explicit Runtime
configuration and are checked against Scope CAS capacity. Event replay is advertised as seven days only when the event flag is
enabled, and zero otherwise. Receiver transport and Native capacity qualification
for large messages remains distinct from Authority acceptance.

Sync timeout ends observation and retains the committed message/operation.
Post-commit observation failure reports `effect_state=committed` with its original
operation reference. A private CAS/key rejection reports no effect. Long requests
refresh the actual OAuth authorization and do not restart a committed send.

## Versions and pagination

Delivery source transactions tick a separate read-model version for message
state, attempts, selected binding, receipts and explicit replies. A short shared
lock on that version protects each delivery/operation projection. Original text
and embedded first reply are read under the same Authority transaction and each
message's reply relation determines its revision. Technical ACK remains separate
from an explicit peer reply; provider consumption remains unobservable.

Contact versions conservatively invalidate at project scope when their actual
team, membership, manager, Slot or endpoint sources change. This avoids labeling
an independent endpoint update with an unchanged team revision.

With event projection storage adopted, Conversation DTOs use a serialized directed
viewer counter covering messages and that viewer's read/preferences state.
Notice DTOs similarly serialize the notice's own technical source and the actual
recipient/principal's seen state. These versions no longer depend on independently
committing counter sums. Source changes and their projection event intents commit
together; exact retries, no-op writes and rollbacks cannot create an extra fact.
The client-only compatibility path remains separate from this opt-in projection
adoption.

Opaque page tokens encrypt a compact query digest, actor/namespace-bound query
identity and committed high-water boundary with an explicitly adopted private
key. They do not expose the global sequence and fit the static cursor/snapshot
bounds. Message reply facts are bounded by the same snapshot high water.
Conversation pages reject a continuation when the caller's read/preferences
state changes, including changes during projection, instead of mixing versions.
These legacy page boundaries remain distinct from the opt-in cross-resource
snapshot. With `communication_event_stream` enabled after explicit adoption,
`GET /snapshot` returns frozen three-family metadata, cache expiry and a same-cut
event anchor. Its continuation tokens return those exact pages under fresh
authorization; they do not substitute latest metadata. `GET /events` uses that
anchor or a saved cursor and is advertised only when the event flag is enabled.

`committed_at` is the timestamp recorded in the successfully committed Authority
row, not a separately measured PostgreSQL physical commit instant. Projection
backfill timestamps record explicit adoption time and are not historical commit
timestamps.

## Adopted contracts and recovery

`runtime/client_models.schema.json`, `sdk/client-contracts.ts` and
`docs/client/communication-openapi.yaml` carry the adopted contracts. The OpenAPI
lists P1 and P2 operations; `/meta.features` advertises only the services enabled
in the current deployment. Timestamp corrections are recorded in
`docs/client/communication-contract-adoption.json`: absent drafts have a null
timestamp, persisted drafts require an aware timestamp, and legacy notices keep
an unknown creation time instead of using adoption time. The development
package's original files are preserved.

Receiver recovery commands have a separate durable, authenticated, idempotent
audit operation with original-issuer checks and binding CAS. Pure inspect and
reconcile never repeat Native input. Opt-in lifecycle callbacks verify the
signed Core plan, current enrolled receiver, exact Driver binding and original
journal at the effect boundary. Prepare can create an explicitly reserved fresh
capacity; resume can reconnect a positively proven stopped original context.
Rebind requires an explicitly selected, authorized and observed ready target.
Missing trusted capabilities return typed unavailability. The authenticated
POST `/projects/{project_id}/receivers/{receiver_id}/actions` now submits the
existing recovery command, commits it and advances only that original operation;
it returns202 with an Operation. Idempotency-Key is required; expected_revision
belongs in the body. Prepare/resume additionally require the OAuth runtime.invoke
scope. Rejected admission has no effect; post-commit observation failure retains
the operation reference and a conservative effect state. The SDK exposes the
same action. Lifecycle schema adoption and operator configuration remain
explicit; ordinary startup does not migrate storage. Signed TLS/PG, factory and
controlled Native regressions cover these paths. Actual Native/Host deployment
qualification is recorded separately from implementation. See
[continuity](COMMUNICATION-CONTINUITY.md) for restoration and unknown-effect fences.

Current-feature source producers cover message/reply/delivery, viewer-specific
conversation updates including preferences, read-state/draft, notice creation and
updates, and receiver/capability changes. Their revisions come from the owning
projection, not a fabricated shared counter. The optional attachment ready
producer publishes only owner metadata intents; NativeLink changes publish
minimal metadata in their source transaction. Consistent snapshots, ordered publication and the opt-in
SSE/headless path are described in [event storage](COMMUNICATION-EVENT-STORAGE.md).

The local headless acceptance episode runs the Node SDK's real `fetch` and SSE
reader against a loopback HTTP resource server and isolated PostgreSQL. It covers
one send, an authenticated peer reply command, bounded body/digest continuation,
private writes, checkpoint reconnect, duplicate replay and Grant revocation with
local drafts/pending commands preserved. Its OAuth issuer and Native drivers are
synthetic; the episode makes no production, cross-host, Harness or model
qualification claim. That episode uses optional P2 features. A separate P1-only
consumer exercises the22 required operations with attachments disabled and no P2
calls. Current regression evidence and the adoption state keep
these evidence scopes and Core/Client/actual Orca milestones separate.

The full OpenAPI retains35 operations with explicit tier annotations.
[The generated P1 contract](../client/communication-p1-openapi.yaml) selects22
required operations;13 optional operations remain in the full contract. It does
not advertise Runtime availability. Message, conversation, receiver and notice
paging retain an explicitly supplied, validated snapshot token exactly. A page
cursor cannot substitute for the original snapshot anchor.

## NativeLink and Host ownership

Runtime `communication_native_links` is an explicit optional limits object; the
HTTP flag independently defaults off. Enabling the metadata API requires the
existing client API, adopted NativeLink storage and a server-injected admitted
NativeProviderRegistry. A caller body cannot select a backend or grant Host
permission. Link/history/receipt/metadata limits are advertised, with zero
capacity while disabled.

Writes correlate the actual current Slot/Scope/endpoint epoch, registered
provider, Host and Native generation. Existing successful request keys are read
under current authority over the link's recorded immutable Scope/address before
consulting a newly assigned endpoint. Metadata association does not grant Native
transcript or action rights. Original handoff evidence is separately required
for message/input SourceLink provenance.

The SDK's [Orca receiver bridge](../../sdk/ORCA-RECEIVER-INTEGRATION.md) requires
independent current Host authorization, the existing signed Receiver verifier
adapter and an atomic current-child input-owner Host extension. Unprovided ports
are explicitly unavailable. Protocol tests and typed delegates do not qualify
an actual Orca Host; the pinned public API's missing extension remains recorded.

## Attachments

Runtime `communication_attachments` is an optional configuration object, default
`null`. HTTP `communication_attachments` is a separate boolean, default `false`,
requiring the client facade and explicit Runtime configuration. Runtime defaults
are 20 MiB/file, eight/message, 50 MiB/message, 100 MiB private unassociated bytes
per viewer, 1 GiB/project and a 24-hour reservation lifetime. These are configured
limits, not claims about a Harness. Every admitted Scope CAS must accommodate the
configured file limit; existing 16 MiB Artifact settings are preserved and must be
explicitly changed by the operator before selecting a 20 MiB attachment service.

POST `/projects/{p}/attachments` reserves immutable name/type/size/SHA-256 for the
actual viewer/address/Scope. PUT `/{id}/content` accepts an unencoded full binary
`application/octet-stream` body; its wire type is distinct from the reservation's
actual PNG/JSON/text media type. The service stores deterministic bounded temporary
chunks in short authorized PostgreSQL transactions and never holds SQL while
waiting for the next upload fragment. POST `/{id}/finalize` verifies size, digest
and bounded format evidence, publishes through the existing Scope CAS outside SQL,
then commits the immutable ready reference with current lease/revision fencing.
These three writes require an opaque Idempotency-Key and have no public If-Match.
Server-owned relative upload paths carry no credentials.

Durable plans preserve the first operation's internal lease and revision. Full
retries replay exact chunks, or verify the duplicate body's actual bytes before
returning the original outcome. A new key is an explicit replacement attempt for
an unaccepted upload; old generations cannot append. Finalize result and ready
state commit together. Concurrent finalizers converge only on an actual identical
ready resource. Rejected content cannot become ready; expired unassociated staging
is cleaned by Runtime maintenance, including external Native-dispatch mode.
Pinned accepted content and its CAS bytes are retained.

GET `/{id}` and `/{id}/content` keep staging and private ready resources visible
only to the actual uploader viewer. A message commit freezes ordered AttachmentRef
metadata in its signed Packet and pins all references atomically with message,
reply indexes and dedup. The catalog now identifies the extended send/read
contract. Empty attachment fields remain absent from legacy Packet serialization
and raw request identity. Drafts may refer to their uploader's pending or ready
objects without pinning or sharing; original draft-write retries precede fresh
attachment expiry admission.

After explicit message association, a generic upload is readable under the
current message participant ACL and artifact-read permission. It does not grant
arbitrary Source access. Incoming shared IDs do not acquire uploader ownership
for forwarding; an explicit authorized download/upload creates a new owned ID.
Repository Source imports remain governed by their separate Source permissions
and location semantics. There is no arbitrary URL or server-local path importer.
Downloads verify complete bytes before releasing them, reauthorize after CAS and
use no-store, nosniff and safe RFC5987 attachment headers. Range downloads and
partial/range upload protocols are not implemented.

Current installed Native paths are text-only for this feature. An authorized
invoke with attachments retains the requested activation and the actual Authority
Inbox commitment, with terminal Native unsupported status. It still requires the
normal invoke permission and binding checks. Node, Adapter, signed receiver and
bridge entrypoints reject before new Native markers/input; old ACK/possible-effect
records are preserved. Waiting for an actual reply cannot remove this hold.
Blob availability does not qualify Native attachment delivery.


## Original-message Native provenance

GET `/projects/{project_id}/messages/{message_handle}?include_native_source=true`
adds optional `native_source` to ReadMessageResponse. The query is a strict
boolean; omission/false preserves the ordinary read. Native-link support must be
enabled. `/meta` advertises `native_source` with `native_links`; availability for
an individual original message remains evidence-dependent.

The server authorizes the actual participant, verifies the committed Core
outbox/operation/dedup/event/acceptance chain and resolves the attempt from the
immutable `runtime_dispatched` receipt. It does not select the latest attempt,
current NativeLink or a similar message. A single matching server provider
registration supplies one trusted DriverJournal or `RemoteNativeSourceReader`.
A local existing-session provider can supply its actual Adapter/Driver journal
without contacting Native. The remote reader uses the configured authenticated
Receiver endpoint's original signed dispatch and a fresh signed readback. It
accepts no caller-selected locator or filesystem path. The Receiver reads its
original journal or installed Orca backend's original Host receipt and returns
only bounded provenance references through the existing TLS receipt protocol.
Ambiguous/missing/changed registrations and missing/corrupt records are typed
unavailability. The journal opens with SQLite `mode=ro`; a missing file is never
created. Current Core ACL and registration identity are checked around the read
and current message permission is checked for unavailable results as well.

`available: true` includes a SourceLink and evidence ref derived from the exact
original handoff, Driver ACK and protocol response. Codex exposes the observed
turn reference; OpenCode requires its exact acknowledged message readback.
HTTP204 alone is insufficient. SourceLink's `operationId` is the original Core
operation; the private Driver operation remains the original invocation id.

The Receiver independently checks current enrolled-node technical-read policy,
including cached results; the original sender's expired input deadline does not
renew execution authority or hide an existing original receipt. The Core checks
current message ACL and provider-registration identity around remote I/O.

This endpoint returns provenance metadata only. Host transcript/tool/Diff/action
permissions remain owned by the separately authenticated NativeView provider.
It performs no Native input, session creation or Inbox/read-state mutation.
Actual Orca Host qualification remains a separate deployment observation.
