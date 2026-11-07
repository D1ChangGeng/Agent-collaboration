import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { createCommunicationState, LocalWorkArchiveQuotaError, projectionKey, reduceCommunication, validateCommunicationEvent } from "../communication-state.ts";

const project = "synthetic-project";
const auth = "synthetic-auth-1";
const messageRef = "message:synthetic-project:original";
const conversationRef = "synthetic-conversation";

function snapshot(overrides = {}) {
  return { snapshot_id: "synthetic-snapshot", snapshot_expires_at: "2999-01-01T00:00:00Z", after_cursor: "snapshot-position",
    auth_revision: auth, actor: { address: "synthetic-principal", principal_ref: "synthetic-principal", level: "client",
      agent_slot_id: null, auth_revision: auth, allowed_actions: ["read_message"] },
    contacts: [{ address: "collaborator:synthetic-project:peer", display_name: "Synthetic peer", agent_slot_id: "peer",
      manager_handle: null, role: null, scope_handles: [], receiver_refs: [], is_self: false, revision: 1 }],
    conversations: [{ conversation_id: conversationRef, project_id: project, participants: ["synthetic-principal", "synthetic-peer"],
      last_message_handle: null, last_activity_at: null, unread_count: 0, revision: 7, archived: false, muted: false }],
    receivers: [], notice_count: 0, pages: { contacts_cursor: null, conversations_cursor: null, receivers_cursor: null }, ...overrides };
}
function initial(options) {
  return reduceCommunication(createCommunicationState(project, options), { type: "snapshot", snapshot: snapshot() });
}
function event(kind, revision, overrides = {}) {
  return { schema_version: "acs-event/1", event_id: kind + ":" + revision, cursor: "opaque-position-" + kind + ":" + revision,
    project_id: project, kind, resource_ref: messageRef, resource_revision: revision, committed_at: "2026-11-06T00:00:00Z",
    auth_revision: auth, payload: {}, ...overrides };
}
function apply(state, value) { return reduceCommunication(state, { type: "event", event: value }); }
function message(revision, content = "Original synthetic content") {
  return { message_handle: messageRef, project_id: project, conversation_id: conversationRef, sender: "synthetic-sender", to: "synthetic-peer",
    content: { text: content, offset: 0, next_offset: null, total_bytes: Buffer.byteLength(content), digest: createHash("sha256").update(content).digest("hex") },
    reply_to: [], attachment_refs: [], conversation_sequence: "1", committed_at: "2026-11-06T00:00:00Z", revision,
    source: "acs_agent", first_reply_handle: null };
}
function hydrate(state, plane, ref, revision, value, extras = {}) {
  return reduceCommunication(state, { type: "projection", plane, resourceRef: ref, revision, value, authRevision: auth, ...extras });
}

test("a snapshot is required before metadata events can populate private state", () => {
  const empty = createCommunicationState(project);
  assert.equal(apply(empty, event("message.committed", 1)), empty);
  assert.equal(empty.cursors.acs, null);
  const source = snapshot();
  const loaded = reduceCommunication(empty, { type: "snapshot", snapshot: source });
  source.contacts[0].display_name = "Caller mutation";
  assert.equal(loaded.resources.get(projectionKey("contact", source.contacts[0].address)).value.display_name, "Synthetic peer");
  assert.equal(loaded.requiresSnapshot, false);
  assert.equal(empty.resources.size, 0);
  assert.throws(() => reduceCommunication(empty, { type: "snapshot", snapshot: snapshot({ snapshot_expires_at: "1970-01-01T00:00:00Z" }) }), TypeError);
});

test("message and delivery versions never overwrite one another or synthesize replies", () => {
  const base = hydrate(initial(), "message", messageRef, 1, message(1));
  let state = apply(base, event("delivery.changed", 90));
  state = apply(state, event("reply.linked", 2, { payload: { message_handle: messageRef } }));
  assert.equal(state.invalidations.get(projectionKey("delivery", messageRef)).revision, 90);
  assert.equal(state.invalidations.get(projectionKey("message", messageRef)).revision, 2);
  const original = state.resources.get(projectionKey("message", messageRef));
  assert.equal(original.revision, 1);
  assert.equal(original.stale, true);
  assert.equal(original.requiredRevision, 2);
  assert.equal(original.value.first_reply_handle, null);
  assert.equal(state.resources.size, base.resources.size);
  state = hydrate(state, "message", messageRef, 3, message(3, "Authorized newer content projection"));
  assert.equal(state.resources.get(projectionKey("message", messageRef)).stale, false);
  const old = hydrate(state, "message", messageRef, 2, message(2, "Stale read must not replace current content"));
  assert.equal(old, state);
  assert.equal(base.resources.get(projectionKey("message", messageRef)).revision, 1);
});

test("draft/read/preferences have independent versions and conversation source signals do not become composite revisions", () => {
  let state = initial();
  state = hydrate(state, "draft", conversationRef, 5, { content: "Server draft", attachment_refs: [], revision: 5, updated_at: null });
  state = hydrate(state, "read_state", conversationRef, 2, { conversation_id: conversationRef, through_message_handle: null, unread_override: false, revision: 2 });
  state = hydrate(state, "preferences", conversationRef, 20, { muted: true, archived: false, revision: 20 });
  state = apply(state, event("draft.changed", 6, { resource_ref: conversationRef }));
  state = apply(state, event("read_state.changed", 1, { resource_ref: conversationRef }));
  assert.equal(state.resources.get(projectionKey("draft", conversationRef)).requiredRevision, 6);
  assert.equal(state.resources.get(projectionKey("read_state", conversationRef)).stale, false);
  assert.equal(state.resources.get(projectionKey("preferences", conversationRef)).revision, 20);
  const signal = event("conversation.updated", 1, { resource_ref: conversationRef, event_id: "source-conversation-invalidation" });
  state = apply(state, signal);
  assert.equal(state.resources.get(projectionKey("conversation", conversationRef)).revision, 7);
  assert.equal(state.resources.get(projectionKey("conversation", conversationRef)).stale, true);
  const newView = { ...snapshot().conversations[0], revision: 8 };
  state = hydrate(state, "conversation", conversationRef, 8, newView);
  assert.equal(state.resources.get(projectionKey("conversation", conversationRef)).stale, true);
  state = hydrate(state, "conversation", conversationRef, 8, newView, { observedEventId: signal.event_id });
  assert.equal(state.resources.get(projectionKey("conversation", conversationRef)).stale, false);
});

test("bounded event-id LRU and per-resource versions prevent duplicate or evicted stale rollback", () => {
  let state = initial({ maxEventIds: 2 });
  const a = event("message.committed", 2, { event_id: "a", cursor: "position-a" });
  state = apply(state, a);
  state = apply(state, event("delivery.changed", 4, { event_id: "b", cursor: "position-b" }));
  state = apply(state, event("draft.changed", 3, { event_id: "c", cursor: "position-c", resource_ref: conversationRef }));
  assert.equal(state.eventIds.size, 2);
  assert.equal(state.eventIds.has("a"), false);
  const replay = apply(state, event("message.committed", 1, { event_id: "a", cursor: "old-position-a" }));
  assert.equal(replay.invalidations.get(projectionKey("message", messageRef)).revision, 2);
  assert.equal(replay.cursors.acs, "position-c");
  const duplicate = apply(replay, event("draft.changed", 3, { event_id: "c", cursor: "old-position-c", resource_ref: conversationRef }));
  assert.equal(duplicate.cursors.acs, "position-c");
  assert.equal(duplicate.eventIds.size, 2);
});

test("permission/resync/auth loss clears server state and cursors but preserves unsent drafts and exact pending commands", () => {
  let state = hydrate(initial(), "message", messageRef, 1, message(1));
  state = reduceCommunication(state, { type: "localDraft", conversationId: conversationRef, value: { content: "Unsent local text", attachments: [] } });
  state = reduceCommunication(state, { type: "pendingCommand", clientRequestId: "request-identity", value: { client_request_id: "request-identity", operation_ref: "original-operation", body: "Keep exact original command" } });
  state = reduceCommunication(state, { type: "nativeCursor", source: "native-provider-a", cursor: "native-position" });
  for (const action of [
    { type: "event", event: event("permission.changed", 0, { resource_ref: null }) },
    { type: "event", event: event("resync.required", 0, { resource_ref: null }) },
    { type: "event", event: event("stream.end", 0, { resource_ref: null, payload: { reset_required: true } }) },
    { type: "event", event: event("delivery.changed", 2, { auth_revision: "new-auth-context" }) },
    { type: "invalidate", reason: "authentication_lost" },
  ]) {
    const reset = reduceCommunication(state, action);
    assert.equal(reset.requiresSnapshot, true);
    assert.equal(reset.authRevision, null);
    assert.equal(reset.actor, null);
    assert.equal(reset.cursors.acs, null);
    assert.equal(reset.cursors.native.size, 0);
    assert.equal(reset.resources.size, 0);
    assert.equal(reset.invalidations.size, 0);
    assert.equal(reset.localDrafts, state.localDrafts);
    assert.equal(reset.pendingCommands, state.pendingCommands);
    assert.equal(reset.pendingCommands.get("request-identity").operation_ref, "original-operation");
    assert.equal(apply(reset, event("message.committed", 10)), reset);
  }
});

test("ACS and each Native source keep separate opaque positions with no numeric or lexical ordering", () => {
  let state = initial();
  state = reduceCommunication(state, { type: "nativeCursor", source: "provider-a", cursor: "999999-native" });
  state = reduceCommunication(state, { type: "nativeCursor", source: "provider-b", cursor: "000001-native" });
  state = apply(state, event("message.committed", 1, { cursor: "z-acs-position" }));
  state = apply(state, event("delivery.changed", 1, { cursor: "a-acs-position" }));
  assert.equal(state.cursors.acs, "a-acs-position");
  assert.equal(state.cursors.native.get("provider-a"), "999999-native");
  assert.equal(state.cursors.native.get("provider-b"), "000001-native");
});

test("a late snapshot cannot rewind live projections or a consumed stream position", () => {
  let state = initial();
  state = apply(state, event("message.committed", 2, { cursor: "current-position" }));
  assert.equal(reduceCommunication(state, { type: "snapshot", snapshot: snapshot() }), state);
  const reset = reduceCommunication(state, { type: "invalidate", reason: "explicit_refresh" });
  const fresh = reduceCommunication(reset, { type: "snapshot", snapshot: snapshot({ snapshot_id: "new-snapshot", after_cursor: "new-authorized-position", auth_revision: "new-auth" }) });
  assert.equal(fresh.cursors.acs, "new-authorized-position");
  assert.equal(fresh.authRevision, "new-auth");
});

test("unsafe event metadata or another project cannot introduce DTO bodies or Driver journals", () => {
  const state = initial();
  for (const value of [event("message.committed", 1, { payload: { content: "Untrusted inline body" } }),
    event("receiver.observed", 1, { payload: { driver_journal: "Unrequested Native transcript" } }),
    event("message.committed", Number.MAX_SAFE_INTEGER + 1), event("unknown.kind", 1),
    { ...event("message.committed", 1), extra_context: "forged" },
    event("message.committed", 1, { payload: { reason_code: "x".repeat(8193) } })]) {
    assert.throws(() => validateCommunicationEvent(value), TypeError);
  }
  assert.throws(() => apply(state, event("message.committed", 1, { project_id: "other-project" })), TypeError);
  assert.equal(state.resources.size, 2);
  assert.throws(() => hydrate(state, "message", messageRef, 5, message(1)), TypeError);
  assert.throws(() => hydrate(state, "message", messageRef, 1, { ...message(1), project_id: "foreign-project" }), TypeError);
});

test("server-cache capacity fails closed while preserving caller-owned local work", () => {
  let state = initial({ maxResources: 3 });
  state = reduceCommunication(state, { type: "localDraft", conversationId: conversationRef, value: "Keep me" });
  state = apply(state, event("message.committed", 1));
  state = apply(state, event("delivery.changed", 1));
  assert.equal(state.requiresSnapshot, true);
  assert.equal(state.resetReason, "cache_capacity_exceeded");
  assert.equal(state.localDrafts.get(conversationRef), "Keep me");
});

function viewerSnapshot(slot, principal = "shared-principal", authRevision = auth, address = principal) {
  return snapshot({ auth_revision: authRevision, actor: { address, principal_ref: principal, level: slot === null ? "client" : "agent",
    agent_slot_id: slot, auth_revision: authRevision, allowed_actions: [] } });
}
function localWork(state, suffix) {
  state = reduceCommunication(state, { type: "localDraft", conversationId: conversationRef, value: { content: "Unsent " + suffix } });
  return reduceCommunication(state, { type: "pendingCommand", clientRequestId: "same-client-request-id",
    value: { client_request_id: "same-client-request-id", operation_ref: "operation-" + suffix, body: "Exact command " + suffix } });
}
function resnapshot(state, value) {
  return reduceCommunication(reduceCommunication(state, { type: "invalidate", reason: "authentication_changed" }), { type: "snapshot", snapshot: value });
}

test("same-principal Slot switches archive local work instead of inheriting a mutual conversation's draft or command", () => {
  const a1 = localWork(reduceCommunication(createCommunicationState(project), { type: "snapshot", snapshot: viewerSnapshot("slot-a1") }), "A1");
  const a1Owner = a1.localWorkOwner;
  let a2 = resnapshot(a1, viewerSnapshot("slot-a2", "shared-principal", "auth-a2"));
  assert.notEqual(a2.localWorkOwner.key, a1Owner.key);
  assert.equal(a2.localDrafts.size, 0);
  assert.equal(a2.pendingCommands.size, 0);
  assert.equal(a2.archivedLocalWork.get(a1Owner.key).owner.agentSlotId, "slot-a1");
  assert.deepEqual(a2.archivedLocalWork.get(a1Owner.key).localDrafts.get(conversationRef), { content: "Unsent A1" });
  assert.equal(a2.archivedLocalWork.get(a1Owner.key).pendingCommands.get("same-client-request-id").operation_ref, "operation-A1");
  a2 = localWork(a2, "A2");
  const returned = resnapshot(a2, viewerSnapshot("slot-a1", "shared-principal", "auth-a1-new"));
  assert.equal(returned.localWorkOwner.key, a1Owner.key);
  assert.equal(returned.localDrafts.get(conversationRef).content, "Unsent A1");
  assert.equal(returned.pendingCommands.get("same-client-request-id").body, "Exact command A1");
  assert.equal(returned.archivedLocalWork.has(a1Owner.key), false);
  assert.equal(returned.archivedLocalWork.get(a2.localWorkOwner.key).localDrafts.get(conversationRef).content, "Unsent A2");
});

test("other principals and different Client addresses do not inherit active local work", () => {
  for (const [before, after] of [
    [viewerSnapshot("slot-a", "principal-a"), viewerSnapshot("slot-a", "principal-b")],
    [viewerSnapshot(null, "shared-principal", auth, "client:project:a"), viewerSnapshot(null, "shared-principal", auth, "client:project:b")],
  ]) {
    const original = localWork(reduceCommunication(createCommunicationState(project), { type: "snapshot", snapshot: before }), "original");
    const switched = resnapshot(original, after);
    assert.equal(switched.localDrafts.size, 0);
    assert.equal(switched.pendingCommands.size, 0);
    assert.equal(switched.archivedLocalWork.get(original.localWorkOwner.key).pendingCommands.size, 1);
  }
});

test("same-viewer authorization refresh keeps active local work without archiving or changing its owner key", () => {
  const original = localWork(reduceCommunication(createCommunicationState(project), { type: "snapshot", snapshot: viewerSnapshot("stable-slot") }), "same-viewer");
  const refreshed = resnapshot(original, viewerSnapshot("stable-slot", "shared-principal", "new-auth-revision"));
  assert.equal(refreshed.localWorkOwner.key, original.localWorkOwner.key);
  assert.equal(refreshed.localDrafts, original.localDrafts);
  assert.equal(refreshed.pendingCommands, original.pendingCommands);
  assert.equal(refreshed.archivedLocalWork.size, 0);
  assert.equal(refreshed.authRevision, "new-auth-revision");
});

test("work created before any viewer snapshot remains in an explicit unowned bucket", () => {
  const unowned = localWork(createCommunicationState(project), "before-login");
  assert.equal(unowned.localWorkOwner, null);
  const current = reduceCommunication(unowned, { type: "snapshot", snapshot: viewerSnapshot("current-slot") });
  assert.equal(current.localDrafts.size, 0);
  assert.equal(current.pendingCommands.size, 0);
  const [bucket] = current.archivedLocalWork.values();
  assert.equal(bucket.owner.kind, "unowned");
  assert.equal(bucket.owner.principalRef, null);
  assert.equal(bucket.localDrafts.get(conversationRef).content, "Unsent before-login");
  const refreshed = resnapshot(current, viewerSnapshot("current-slot", "shared-principal", "refreshed-auth"));
  assert.equal(refreshed.localDrafts.size, 0);
  assert.equal(refreshed.archivedLocalWork.get(bucket.owner.key), bucket);
});

test("archive owner and byte quotas throw without deleting any prior or active local work", () => {
  let a = localWork(reduceCommunication(createCommunicationState(project, { maxArchivedOwners: 1 }), { type: "snapshot", snapshot: viewerSnapshot("a") }), "A");
  a = resnapshot(a, viewerSnapshot("b"));
  const b = localWork(a, "B");
  const pending = reduceCommunication(b, { type: "invalidate", reason: "switch" });
  assert.throws(() => reduceCommunication(pending, { type: "snapshot", snapshot: viewerSnapshot("c") }),
    error => error instanceof LocalWorkArchiveQuotaError && error.reason === "owner_limit");
  assert.equal(pending.pendingCommands.get("same-client-request-id").operation_ref, "operation-B");
  assert.equal([...pending.archivedLocalWork.values()][0].pendingCommands.get("same-client-request-id").operation_ref, "operation-A");
  let large = reduceCommunication(createCommunicationState(project, { maxArchivedBytes: 1024 }), { type: "snapshot", snapshot: viewerSnapshot("large") });
  large = reduceCommunication(large, { type: "localDraft", conversationId: conversationRef, value: "x".repeat(2048) });
  const oldDrafts = large.localDrafts;
  assert.throws(() => resnapshot(large, viewerSnapshot("another")), error => error instanceof LocalWorkArchiveQuotaError && error.reason === "byte_limit");
  assert.equal(large.localDrafts, oldDrafts);
  assert.equal(large.archivedLocalWork.size, 0);
});

test("acknowledged noncomparable same-revision refresh stores the authorized new Receiver DTO defensively", () => {
  const old = { receiver_id: "fixture-receiver", address: "collaborator:synthetic-project:peer", binding_epoch: 1, revision: 1,
    native_session_ref: "fixture-old-session", capability_scope: { adapter_id: "fixture", adapter_version: "1", harness_kind: "fixture",
      harness_version: null, execution_host_ref: "fixture-host", binary_digest: null, config_digest: null, connection_epoch: 1, provider_generation: null },
    capabilities: [{ name: "native.structured_input", support: "unknown", availability: "unknown", evidence_ref: null, valid_until: null, conditions: [] }],
    observations: [], allowed_actions: ["inspect"] };
  let state = reduceCommunication(createCommunicationState(project), { type: "snapshot", snapshot: snapshot({ receivers: [old] }) });
  const signal = event("receiver.observed", 1, { resource_ref: old.receiver_id, event_id: "fixture-receiver-invalidation" });
  state = apply(state, signal);
  const fresh = { ...old, native_session_ref: "fixture-authorized-new-session", capabilities: [{ ...old.capabilities[0],
    support: "supported", availability: "available", evidence_ref: "fixture-authorized-readback", valid_until: "2999-01-01T00:00:00Z" }] };
  const unacknowledged = hydrate(state, "receiver", old.receiver_id, 1, fresh);
  assert.equal(unacknowledged.resources.get(projectionKey("receiver", old.receiver_id)).stale, true);
  const updated = hydrate(state, "receiver", old.receiver_id, 1, fresh, { observedEventId: signal.event_id });
  fresh.native_session_ref = "Caller mutation";
  fresh.capabilities[0].support = "unsupported";
  const current = updated.resources.get(projectionKey("receiver", old.receiver_id));
  assert.equal(current.stale, false);
  assert.equal(current.revision, 1);
  assert.equal(current.value.native_session_ref, "fixture-authorized-new-session");
  assert.equal(current.value.capabilities[0].support, "supported");
  const lower = hydrate(updated, "receiver", old.receiver_id, 0, { ...old, revision: 0 }, { observedEventId: signal.event_id });
  assert.equal(lower, updated);
});
