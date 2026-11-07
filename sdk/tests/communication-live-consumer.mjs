// Test-only consumer: real fetch/TCP, production SDK modules, JSON-line fixture coordination.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createInterface } from "node:readline";
import { pathToFileURL } from "node:url";
import { createCommunicationState, projectionKey, reduceCommunication } from "../communication-state.ts";
import { CommunicationEventStream } from "../communication-stream.ts";
import { HttpCommunicationClient } from "../communication-client.ts";

const base = process.env.ACS_HEADLESS_TEST_URL;
const token = process.env.ACS_HEADLESS_TEST_BEARER;
const project = process.env.ACS_HEADLESS_TEST_PROJECT;
const peer = process.env.ACS_HEADLESS_TEST_PEER;
const prefix = "/api/communication/v1/projects/" + encodeURIComponent(project);
const content = "HEADLESS_LIVE_OUTGOING_BODY_🧭" + "字".repeat(6000);
const replyText = "HEADLESS_LIVE_PEER_REPLY_BODY_🧭";
const localText = "HEADLESS_LOCAL_UNSENT_BODY";
const draftText = "HEADLESS_SERVER_DRAFT_BODY_1";
const draftText2 = "HEADLESS_SERVER_DRAFT_BODY_2";
const attachmentBytes = Buffer.from("HEADLESS_ATTACHMENT_PRIVATE_BYTES_汉字🧭".repeat(2500), "utf8");
const attachmentName = "headless-private-附件.txt";
const forbidden = ["HEADLESS_LIVE_OUTGOING_BODY", "HEADLESS_LIVE_PEER_REPLY_BODY", "HEADLESS_SERVER_DRAFT_BODY", localText,
  "HEADLESS_ATTACHMENT_PRIVATE_BYTES", attachmentName];
const nonce = "headless-live-send-" + process.pid;
const pending = new Map();
let input;
let client;
let sequence = 0, phase = "initialization", state, original, conversation, authRevision;
let busy = 0, duplicateEvents = 0, emittedEvents = 0, readBodies = 0, sendRequests = 0, snapshotRequired = false;
const kinds = new Map();
const resources = new Set();
const pumps = new Set();
const report = value => process.stdout.write(JSON.stringify(value) + "\n");
function receiveControl(line) {
  let value;
  try { value = JSON.parse(line); } catch { return; }
  const waiting = pending.get(value.id);
  if (!waiting) return;
  pending.delete(value.id); clearTimeout(waiting.timer);
  if (value.ok) waiting.resolve(value.result); else waiting.reject(new Error("Fixture coordination failed"));
}

function ask(action, data = {}) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error("Fixture coordination timeout")); }, 20000);
    pending.set(id, { resolve, reject, timer });
    report({ type: "request", id, action, ...data });
  });
}
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
/** Test observer supervision: preserve a failed/ended connection instead of masking it as a deadline. */
export async function waitForObservation(predicate, label, { milliseconds = 20000, observer, expectSnapshot = false } = {}) {
  const end = performance.now() + milliseconds;
  while (true) {
    if (observer?.failure) throw observer.failure;
    if (observer?.snapshotRequired && !expectSnapshot) throw observer.snapshotRequired;
    if (observer?.completed && !(expectSnapshot && observer.snapshotRequired)) {
      throw Object.assign(new Error("Headless observer ended before its required episode"), { code: "observer_ended", stage: label });
    }
    if (predicate()) return;
    const remaining = end - performance.now();
    if (remaining <= 0) throw Object.assign(new Error("Headless stage timeout"), { code: "stage_timeout", stage: label });
    await sleep(Math.min(20, remaining));
  }
}
async function quietCheckpoint(observer) {
  let count = emittedEvents, stableSince = performance.now();
  await waitForObservation(() => {
    if (count !== emittedEvents || busy) { count = emittedEvents; stableSince = performance.now(); }
    return busy === 0 && performance.now() - stableSince >= 1000;
  }, "published_event_tail", { observer });
}
function hydrate(plane, ref, value, observedEventId) {
  state = reduceCommunication(state, { type: "projection", plane, resourceRef: ref, revision: value.revision,
    value, authRevision, observedEventId });
}
async function readMessage(ref) {
  const complete = await client.readMessageComplete(project, ref, { maxInlineBytes: 4096, maxBytes: 1024 * 1024 });
  const first = complete.first;
  assert.equal(first.message.message_handle, ref);
  if (original && ref === original.message_handle) assert.equal(complete.text, content);
  hydrate("message", ref, first.message);
  if (first.first_reply) {
    assert.equal(first.first_reply.message_handle, first.message.first_reply_handle);
    hydrate("message", first.first_reply.message_handle, first.first_reply);
  }
  readBodies++;
  return { result: first, text: complete.text };
}
async function observe(value) {
  const wire = JSON.stringify(value);
  assert.ok(forbidden.every(text => !wire.includes(text)));
  const duplicate = state.eventIds.has(value.event_id);
  const before = state.resources;
  const cursorBefore = state.cursors.acs;
  state = reduceCommunication(state, { type: "event", event: value });
  emittedEvents++;
  if (value.payload.reset_required || value.kind === "permission.changed" || value.kind === "resync.required") return;
  if (duplicate) {
    duplicateEvents++;
    assert.equal(state.resources, before);
    assert.equal(state.cursors.acs, cursorBefore);
    return;
  }
  busy++;
  try {
    if (value.kind === "message.committed" || value.kind === "reply.linked") {
      await readMessage(value.resource_ref);
    } else if (value.kind === "delivery.changed") {
      const current = await client.delivery(project, value.resource_ref);
      hydrate("delivery", value.resource_ref, current);
    } else if (value.kind === "draft.changed" || value.kind === "read_state.changed") {
      const current = value.kind === "draft.changed" ? await client.draft(project, value.resource_ref) : await client.readState(project, value.resource_ref);
      hydrate(value.kind === "draft.changed" ? "draft" : "read_state", value.resource_ref, current);
    } else if (value.kind === "conversation.updated") {
      const current = await client.conversation(project, value.resource_ref);
      hydrate("conversation", value.resource_ref, current, value.event_id);
    } else if (value.kind === "notice.created" || value.kind === "notice.updated") {
      const page = await client.notices(project);
      const current = page.items.find(item => item.notice_handle === value.resource_ref);
      if (current) hydrate("notice", value.resource_ref, current, value.event_id);
    } else if (value.kind === "receiver.observed" || value.kind === "capability.changed") {
      const current = await client.receiver(project, value.resource_ref);
      hydrate(value.kind === "receiver.observed" ? "receiver" : "capability", value.resource_ref, current, value.event_id);
    } else if (value.kind === "attachment.ready") {
      const current = await client.attachment(project, value.resource_ref);
      hydrate("attachment", value.resource_ref, current, value.event_id);
    }
    kinds.set(value.kind, (kinds.get(value.kind) ?? 0) + 1);
    resources.add(value.resource_ref);
  } finally { busy--; }
}
function pump(after, lastEventId) {
  const controller = new AbortController();
  const stream = new CommunicationEventStream({ projectId: project, url: new URL(prefix + "/events", base),
    getBearer: () => token, afterCursor: after, lastEventId, authRevision });
  const entry = { controller, stream, done: null, failure: null, snapshotRequired: null, completed: false,
    eventCount: 0, duplicateCount: 0 };
  pumps.add(entry);
  entry.done = (async () => {
    try {
      for await (const value of stream.events({ signal: controller.signal })) {
        entry.eventCount++;
        if (state.eventIds.has(value.event_id)) entry.duplicateCount++;
        await observe(value);
      }
    } catch (error) {
      if (error.requiresSnapshot) {
        entry.snapshotRequired = error;
        snapshotRequired = true;
        state = reduceCommunication(state, { type: "invalidate", reason: error.reason ?? "snapshot_required" });
      } else if (error.code !== "aborted") entry.failure = error;
    } finally { entry.completed = true; pumps.delete(entry); }
  })();
  return entry;
}
async function stop(entry) { entry.controller.abort(); await entry.done; if (entry.failure) throw entry.failure; }

async function main() {
  if (!base || !token || !project || !peer || new URL(base).hostname !== "127.0.0.1") throw new Error("Missing owned local test configuration");
  input = createInterface({ input: process.stdin });
  input.on("line", receiveControl);
  client = new HttpCommunicationClient({ endpoint: new URL("/api/communication/v1/", base), getBearer: () => token });
  phase = "metadata_snapshot";
  const metadata = await client.meta();
  assert.ok(["snapshot", "events", "attachments"].every(feature => metadata.features.includes(feature)));
  assert.ok(attachmentBytes.length <= metadata.limits.attachment_bytes && attachmentBytes.length > 65536);
  const profile = await client.profile();
  const snapshot = await client.snapshotView(project);
  assert.equal(profile.principal_ref, snapshot.actor.principal_ref);
  authRevision = snapshot.auth_revision;
  state = reduceCommunication(createCommunicationState(project), { type: "snapshot", snapshot });
  conversation = (await client.resolveConversation(project, peer)).conversation_id;
  state = reduceCommunication(state, { type: "localDraft", conversationId: conversation, value: { content: localText } });
  phase = "actual_attachment_reserve_upload_finalize";
  const declaration = { name: attachmentName, media_type: "text/plain", bytes: attachmentBytes.length,
    sha256: createHash("sha256").update(attachmentBytes).digest("hex") };
  const reservation = await client.reserveAttachment(project, declaration, nonce + "-attachment-reserve");
  const uploaded = await client.uploadAttachment(project, reservation, attachmentBytes, nonce + "-attachment-upload");
  assert.equal(uploaded.state, "uploaded");
  const finalized = await client.finalizeAttachment(project, reservation.attachment_id,
    { bytes: declaration.bytes, sha256: declaration.sha256 }, nonce + "-attachment-finalize");
  assert.equal(finalized.state, "ready");
  assert.deepEqual(Buffer.from((await client.downloadAttachment(project, finalized)).bytes), attachmentBytes);
  const request = { to: peer, content, activation: "message_only", attachment_refs: [finalized.attachment_id] };
  state = reduceCommunication(state, { type: "pendingCommand", clientRequestId: nonce,
    value: { client_request_id: nonce, request, operation_ref: null } });
  const owner = state.localWorkOwner.key;
  const first = pump(snapshot.after_cursor);
  phase = "actual_send_and_peer_reply";
  sendRequests++;
  const sent = await client.sendMessage(project, request, nonce);
  original = sent.message;
  assert.deepEqual(original.attachment_refs.map(value => value.attachment_id), [finalized.attachment_id]);
  const pinned = await client.attachment(project, finalized.attachment_id);
  assert.equal(pinned.state, "ready"); assert.equal(pinned.expires_at, null); assert.equal(pinned.revision, finalized.revision + 1);
  assert.deepEqual(Buffer.from((await client.downloadAttachment(project, pinned)).bytes), attachmentBytes);
  state = reduceCommunication(state, { type: "pendingCommand", clientRequestId: nonce,
    value: { client_request_id: nonce, request, operation_ref: sent.operation_ref } });
  await ask("publish");
  const reply = await ask("peer_reply", { message_handle: original.message_handle, sender: original.sender });
  assert.equal(reply.attachment_participant_read, true);
  await ask("publish");
  const read = await readMessage(original.message_handle);
  assert.equal(read.result.message.first_reply_handle, reply.message_handle);
  assert.equal(read.result.first_reply.message_handle, reply.message_handle);
  assert.equal(read.result.first_reply.content.text, replyText);
  phase = "private_state_writes";
  const markedRead = await client.markRead(project, conversation, { through_message_handle: reply.message_handle },
    { expectedRevision: 0, requestId: "headless-read" });
  assert.equal(markedRead.through_message_handle, reply.message_handle);
  const preferences = await client.updatePreferences(project, conversation, { muted: true }, { expectedRevision: 0, requestId: "headless-preferences" });
  assert.equal(preferences.muted, true);
  const draft = await client.updateDraft(project, conversation, { content: draftText, attachment_refs: [finalized.attachment_id] },
    { expectedRevision: 0, requestId: "headless-draft-one" });
  assert.equal(draft.content, draftText);
  const notices = await client.notices(project);
  assert.equal(notices.items.length, 1);
  const notice = notices.items[0];
  const seen = await client.markSeen(project, notice.notice_handle, { seen: true }, { expectedRevision: notice.revision, requestId: "headless-seen" });
  assert.equal(seen.seen, true);
  await ask("publish");
  const minimum = ["message.committed", "reply.linked", "delivery.changed", "read_state.changed", "draft.changed", "attachment.ready"];
  await waitForObservation(() => minimum.every(kind => kinds.has(kind)) && busy === 0, "initial_source_events", { observer: first });
  await quietCheckpoint(first);
  if (first.failure) throw first.failure;
  phase = "checkpoint_reconnect";
  const checkpoint = first.stream.resumeCursor;
  assert.ok(checkpoint);
  await stop(first);
  const resumed = pump(checkpoint, checkpoint);
  await client.updateDraft(project, conversation, { content: draftText2, attachment_refs: [finalized.attachment_id] },
    { expectedRevision: 1, requestId: "headless-draft-two" });
  await ask("publish");
  await waitForObservation(() => state.resources.get(projectionKey("draft", conversation))?.revision === 2 && busy === 0,
    "resumed_draft_event", { observer: resumed });
  assert.equal(state.resources.get(projectionKey("draft", conversation)).value.content, draftText2);
  assert.deepEqual(state.resources.get(projectionKey("draft", conversation)).value.attachment_refs, [finalized.attachment_id]);
  await quietCheckpoint(resumed);
  await stop(resumed);
  phase = "at_least_once_duplicate_replay";
  const replay = pump(snapshot.after_cursor);
  await waitForObservation(() => duplicateEvents > 0, "duplicate_replay", { observer: replay });
  await quietCheckpoint(replay);
  phase = "current_grant_revocation";
  await ask("revoke_grant");
  await waitForObservation(() => snapshotRequired, "revocation_control", { observer: replay, expectSnapshot: true });
  await replay.done;
  assert.equal(replay.stream.requiresSnapshot, true);
  assert.equal(state.requiresSnapshot, true);
  assert.equal(state.resources.size, 0);
  assert.equal(state.cursors.acs, null);
  assert.equal(state.localWorkOwner.key, owner);
  assert.equal(state.localDrafts.get(conversation).content, localText);
  assert.equal(state.pendingCommands.get(nonce).client_request_id, nonce);
  assert.equal(state.pendingCommands.get(nonce).operation_ref, sent.operation_ref);
  assert.equal(sendRequests, 1);
  report({ type: "result", evidence: { scenario: "actual-node-sdk-local-oauth-http-pg", node_version: process.version,
    real_fetch: true, actual_tcp_resource_server: true, synthetic_issuer: true, host_qualified: false, model_qualified: false,
    production_http_client: true, attachment_reserved_uploaded_finalized: true, attachment_utf8_bytes: attachmentBytes.length,
    attachment_complete_digest_download: true, attachment_message_pinned: pinned.expires_at === null,
    attachment_participant_read: reply.attachment_participant_read, attachment_draft_refs_preserved: true,
    metadata_profile_snapshot: true, authorized_body_digest_and_continuation: readBodies > 0, actual_peer_reply_link: true,
    read_state_written: markedRead.through_message_handle === reply.message_handle, preferences_written: preferences.muted,
    server_draft_written: draft.content === draftText, notice_seen_written: seen.seen,
    checkpoint_reconnected: true, duplicate_events_ignored: duplicateEvents > 0, duplicate_event_count: duplicateEvents,
    event_kinds: [...kinds.keys()].sort(), metadata_event_count: emittedEvents, body_and_draft_text_absent_from_events: true,
    grant_revocation_requires_snapshot: true, private_cache_cleared: true, local_work_owner_preserved: true,
    local_unsent_draft_preserved: true, exact_pending_command_preserved: true, outbound_send_requests: sendRequests } });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try { await main(); }
  catch (error) {
    const code = typeof error.code === "string" ? error.code : error.name;
    report({ type: "failure", phase, code: /^[a-zA-Z][a-zA-Z0-9_]{0,63}$/.test(code) ? code : "observer_failure",
      status: Number.isInteger(error.status) ? error.status : null,
      reason: typeof error.reason === "string" && /^[a-zA-Z][a-zA-Z0-9_.-]{0,95}$/.test(error.reason) ? error.reason : null,
      stage: typeof error.stage === "string" ? error.stage : null,
      diagnostics: { emitted_events: emittedEvents, duplicate_events: duplicateEvents, busy,
        remembered_event_ids: state?.eventIds.size ?? 0, snapshot_required: snapshotRequired,
        active_observers: [...pumps].map(entry => ({ events: entry.eventCount, duplicates: entry.duplicateCount,
          completed: entry.completed, failed: entry.failure !== null, snapshot_required: entry.snapshotRequired !== null })) } });
    process.exitCode = 1;
  } finally {
    for (const entry of [...pumps]) { entry.controller.abort(); await entry.done; }
    client?.close();
    for (const entry of pending.values()) clearTimeout(entry.timer);
    input?.close(); process.stdin.pause();
  }
}
