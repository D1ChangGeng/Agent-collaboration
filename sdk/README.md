# ACS in-process SDK

`HttpCommunicationClient` uses the existing authenticated communication HTTP API.
It returns DTOs checked against the adopted Runtime schema. Authorization remains
with the server. The caller supplies the ACS endpoint, a current bearer callback
and explicit keys for writes. A write is sent once; the SDK never executes or
resends a stored command.

```ts
import { HttpCommunicationClient } from "./communication-client.ts";

const client = new HttpCommunicationClient({
  endpoint: new URL("/api/communication/v1/", resourceServerOrigin),
  getBearer: () => host.getCurrentAcsBearer(),
});
const captured = await client.snapshotView(projectId);
const accepted = await client.sendMessage(projectId, {
  to: peerAddress,
  content: text,
  activation: "message_only",
}, originalRequestKey);
const complete = await client.readMessageComplete(projectId,
  accepted.message.message_handle, { maxBytes: 1024 * 1024 });
```

Use the advertised `meta()` limits when composing new uploads/messages. Read
budgets are explicit local bounds, so accepted history can still be read when a
deployment later reduces its upload quota. `readMessageComplete` checks UTF-8 byte
offsets, progress, declared total and the complete SHA-256 before returning text.
Paged methods return the actual `page` object; carry both `next_cursor` and
`snapshot_id` into the next call when the family supplies a snapshot. Projects,
routes and ordinary contact pages supply null snapshots and use their own cursor.

Reference limits count Unicode characters, matching JSON Schema and Runtime
string limits. Wire buffers, complete bodies and files retain separate UTF-8
byte limits. This includes identifiers containing supplementary Unicode symbols.

Use stable ASCII request keys for HTTP Idempotency-Key headers. Resource IDs and
message bodies support Unicode through URL encoding and UTF-8 respectively.

Delivery scope follows the v1.1 revision: the22-operation P1 contract is in
`docs/client/communication-p1-openapi.yaml`; existing attachments, personal state,
drafts and search are optional P2. Runtime `meta().features` determines availability.

Native read/list results use a final current Host authorization check and return
owned immutable values. Native event frames are captured before awaited checks.
On Host authorization/session loss, `invalidateNativeState` clears the Native
cursor, selected Session and cached SourceLinks while preserving the ACS cursor.

Attachment stages are separate calls. `uploadAttachment` performs only the
requested full-file PUT; its bytes and declaration are captured before waiting
for credentials or hashing. The transport uses `application/octet-stream` and
the service's reservation metadata. It never follows `upload_path` or imports a
local path/remote URL.

```ts
const reserved = await client.reserveAttachment(projectId, {
  name: displayName, media_type: mediaType,
  bytes: content.byteLength, sha256: contentSha256,
}, originalReserveKey);
await client.uploadAttachment(projectId, reserved, content, originalUploadKey);
const ready = await client.finalizeAttachment(projectId, reserved.attachment_id,
  { bytes: reserved.bytes, sha256: reserved.sha256 }, originalFinalizeKey);
const downloaded = await client.downloadAttachment(projectId, ready);
```

A download verifies complete size, media type, ETag and SHA-256 before exposing
bytes. A private ready upload remains private until the server accepts an actual
message association. Personal draft references neither pin nor share files.

`CommunicationHttpError` exposes a sanitized code, HTTP status, `effectState`,
request ID and any validated operation reference. A network failure or invalid
response after an attempted write has an unknown effect. Keep the original key,
body and operation reference for an explicit caller recovery decision. A server
Problem preserves its recorded effect. Error messages do not copy raw response
bodies or bearer values.

Call `close()` when changing the authenticated host account. New snapshots also
fence operations and streams when their Project, actual actor or authorization
revision changes. Composite reads/uploads keep the generation captured at their
start, including hashing and Blob reads. Server projections and pending local
work remain in the caller-owned `communication-state.ts` reducer; owner changes
archive that local work rather than executing it under another actor.

`events()` uses the existing bounded SSE parser and requires a snapshot auth
revision (captured by `snapshotView` or supplied explicitly). Reconnect and fresh
snapshot decisions stay with the caller. `asPort()` exposes the supplied
CommunicationClient integration shape while retaining actual receipt facts.
Native admission is distinct from an explicit Agent reply.

`nativeLinks(project, { address, limit, cursor, snapshotId })` lists admitted Core
associations. `writeNativeLink(project, linkId, body, originalKey)` sends the
typed nine-field body, including `expected_revision`, expected host and provider
generation. It does not send `If-Match`. The twelve-field result must match the
requested Project, link, receiver, session, host, generation and binding epoch.
These association capability values do not authorize a Host read or action.

`integration-ports.ts` provides typed Native/Workspace/management delegates.
Bind an exact host session and inject current host authorization for each
operation. Absent host operations report typed unavailability; function presence
does not establish a capability. Native rows, source evidence and cursors retain
their host provenance. An ACS bearer or role is not a Native host grant.

Regenerate and check the validation data with
`python tools/runtime/export_sdk_runtime_contracts.py [--check]`. Its source is
`runtime/client_models.schema.json`; no RFC workspace or external schema retrieval
is used. New schema keywords require an explicit validator change. The SDK rejects
unsafe JSON integers rather than silently rounding identifiers or revisions.


`readMessage(project, handle, { includeNativeSource: true })` requests optional
`native_source` metadata from the same authenticated message read. Normal reads
and explicit false do not send the extension query. An available result contains
the original Core operation, receiving binding epoch, admitted provider/Host,
original session/generation and exact Native input or turn reference. The proof
comes from the original Core dispatch receipt and Driver handoff/ACK/protocol
journal, independently of current NativeLink values or text similarity.

A missing source returns `available: false` with a bounded reason code. This does
not consume Inbox, create or inspect a Native session, or grant a NativeView read,
watch or action permission. Remote provenance uses an explicitly registered
`RemoteNativeSourceReader` over the existing authenticated Receiver readback.
No path, provider URL or replacement session is chosen by the caller.
`SourceLink` in the integration ports now uses the same generated DTO type.
