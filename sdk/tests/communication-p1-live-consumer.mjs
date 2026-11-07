// P1-only consumer: actual production SDK/REST/SSE, no optional P2 calls.
import assert from "node:assert/strict";
import { createInterface } from "node:readline";
import { readFileSync } from "node:fs";
import { HttpCommunicationClient } from "../communication-client.ts";
import { createCommunicationState, reduceCommunication } from "../communication-state.ts";
import { createNativeWorkspaceProvider } from "../integration-ports.ts";

const url = process.env.ACS_P1_TEST_URL, token = process.env.ACS_P1_TEST_BEARER;
if (!url || !token || new URL(url).hostname !== "127.0.0.1") throw new Error("Owned loopback configuration required");
const report = value => process.stdout.write(JSON.stringify(value) + "\n");
const input = createInterface({ input: process.stdin }), pending = new Map(), pumps = new Set();
let initial, id = 0, phase = "configuration", state, snapshotRequired = false, duplicates = 0, sends = 0;
const initialized = new Promise(resolve => { initial = resolve; });
input.on("line", line => {
  const value = JSON.parse(line);
  if (value.type === "configuration") { initial(value); return; }
  const waiter = pending.get(value.id);
  if (waiter) { pending.delete(value.id); clearTimeout(waiter.timer); waiter.resolve(value.result); }
});
function ask(action, values = {}) {
  const key = ++id;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(key); reject(new Error("P1 fixture coordination deadline")); }, 20000);
    pending.set(key, { resolve, reject, timer }); report({ type: "request", id: key, action, ...values });
  });
}
const covered = new Set(), sdk = new HttpCommunicationClient({ endpoint: new URL("/api/communication/v1/", url), getBearer: () => token });
const content = "P1 original natural message 🧭" + "字".repeat(6000), replyText = "P1 explicit peer reply 🧭";
const forbidden = ["P1 original natural message", "P1 explicit peer reply", "P1 continuation message"];
async function call(operation, promise) {
  try { const result = await promise; covered.add(operation); return result; }
  catch (error) { error.testOperation = operation; throw error; }
}
async function until(predicate, observer, label, { reset = false } = {}) {
  const end = performance.now() + 20000;
  while (true) {
    if (observer.failure) throw observer.failure;
    if (observer.reset && !reset) throw observer.reset;
    if (observer.ended && !(reset && observer.reset)) throw Object.assign(new Error("P1 observer ended"), { code: "observer_ended", stage: label });
    if (predicate()) return;
    if (performance.now() >= end) throw Object.assign(new Error("P1 observer deadline"), { code: "stage_timeout", stage: label });
    await new Promise(resolve => setTimeout(resolve, 20));
  }
}
function pump(project, after, authRevision) {
  const controller = new AbortController();
  const entry = { controller, events: [], failure: null, reset: null, ended: false, done: null };
  pumps.add(entry);
  entry.done = (async () => {
    try {
      for await (const event of sdk.events(project, after, { signal: controller.signal, authRevision })) {
        covered.add("subscribeEvents");
        assert.ok(forbidden.every(text => !JSON.stringify(event).includes(text)));
        const duplicate = state.eventIds.has(event.event_id), before = state.resources, cursor = state.cursors.acs;
        state = reduceCommunication(state, { type: "event", event });
        entry.events.push(event);
        if (duplicate) { duplicates++; assert.equal(state.resources, before); assert.equal(state.cursors.acs, cursor); }
      }
    } catch (error) {
      if (error.requiresSnapshot) {
        entry.reset = error; snapshotRequired = true;
        state = reduceCommunication(state, { type: "invalidate", reason: error.reason });
      } else if (!controller.signal.aborted) entry.failure = error;
    } finally { entry.ended = true; pumps.delete(entry); }
  })();
  return entry;
}
async function stop(entry) { entry.controller.abort(); await entry.done; if (entry.failure) throw entry.failure; }

try {
  const { project, peer, receiver, nativeLink } = await initialized;
  phase = "p1_handshake_navigation";
  const meta = await call("getMeta", sdk.meta());
  assert.ok(["snapshot", "events", "native_links"].every(feature => meta.features.includes(feature)));
  assert.equal(meta.features.includes("attachments"), false);
  assert.equal(meta.features.includes("attachment_uploads"), false);
  assert.equal(meta.limits.attachment_count, 0); assert.equal(meta.limits.attachment_total_bytes, 0);
  const profile = await call("getProfile", sdk.profile());
  const projects = await call("listProjects", sdk.projects({ limit: 1 }));
  assert.ok(projects.items.some(item => item.project_id === project));
  await call("listRoutes", sdk.routes(project, { limit: 1 }));
  const contacts = await call("listContacts", sdk.contacts(project, { limit: 1 }));
  assert.ok(contacts.items.length);
  const resolved = await call("resolveConversation", sdk.resolveConversation(project, peer));
  await call("getConversation", sdk.conversation(project, resolved.conversation_id));
  await call("listConversations", sdk.conversations(project, { limit: 1 }));
  phase = "consistent_p1_snapshot_and_pages";
  const snapshot = await call("getSnapshot", sdk.snapshotView(project, { limit: 1 }));
  assert.equal(snapshot.actor.principal_ref, profile.principal_ref);
  state = reduceCommunication(createCommunicationState(project), { type: "snapshot", snapshot });
  for (const [operation, family, cursorName] of [["listContacts", "contacts", "contacts_cursor"],
    ["listConversations", "conversations", "conversations_cursor"], ["listReceivers", "receivers", "receivers_cursor"]]) {
    let cursor = snapshot.pages[cursorName], pages = 0;
    while (cursor) {
      const page = await call(operation, sdk[family](project, { limit: 1, snapshotId: snapshot.snapshot_id, cursor }));
      assert.equal(page.page.snapshot_id, snapshot.snapshot_id); cursor = page.page.next_cursor;
      assert.ok(++pages < 20);
    }
  }
  const receivers = await call("listReceivers", sdk.receivers(project, { limit: 1 }));
  assert.ok(receivers.items.length);
  const receiving = await call("getReceiver", sdk.receiver(project, receiver));
  assert.equal(receiving.receiver_id, receiver);
  const first = pump(project, snapshot.after_cursor, snapshot.auth_revision);
  phase = "normal_message_stable_key_and_explicit_reply";
  const key = "p1-original-" + process.pid, body = { to: peer, content, activation: "message_only" };
  sends++; const sent = await call("sendMessage", sdk.sendMessage(project, body, key));
  sends++; const replayed = await call("sendMessage", sdk.sendMessage(project, body, key));
  assert.equal(replayed.duplicate, true); assert.equal(replayed.operation_ref, sent.operation_ref);
  assert.equal(replayed.message.message_handle, sent.message.message_handle);
  const timed = await call("waitForMessages", sdk.wait(project, { handles: [sent.message.message_handle], timeout_seconds: 0 }));
  assert.equal(timed.wait.state, "timed_out");
  assert.equal(timed.items.length, 1);
  assert.equal(timed.items[0].message_handle, sent.message.message_handle);
  assert.equal(timed.items[0].native.state, "not_requested");
  assert.deepEqual(timed.items[0].response, { present: false, message_handle: null });
  const reply = await ask("peer_reply", { message_handle: sent.message.message_handle, sender: sent.message.sender });
  const satisfied = await call("waitForMessages", sdk.wait(project, { handles: [sent.message.message_handle], timeout_seconds: 0 }));
  assert.equal(satisfied.wait.state, "satisfied");
  assert.equal(satisfied.items.length, 1);
  assert.equal(satisfied.items[0].message_handle, sent.message.message_handle);
  assert.equal(satisfied.items[0].native.state, "not_requested");
  assert.deepEqual(satisfied.items[0].response, { present: true, message_handle: reply.message_handle });
  const full = await call("readMessage", sdk.readMessageComplete(project, sent.message.message_handle, { maxInlineBytes: 4096 }));
  assert.equal(full.text, content); assert.equal(full.first.first_reply.message_handle, reply.message_handle);
  assert.equal(full.first.first_reply.content.text, replyText);
  const history = await call("listMessages", sdk.messages(project, { conversationId: resolved.conversation_id, limit: 1 }));
  assert.equal(history.items.length, 1);
  if (history.page.next_cursor) await call("listMessages", sdk.messages(project,
    { conversationId: resolved.conversation_id, limit: 1, snapshotId: history.page.snapshot_id, cursor: history.page.next_cursor }));
  const delivery = await call("getDelivery", sdk.delivery(project, sent.message.message_handle));
  assert.equal(delivery.native.state, "not_requested"); assert.equal(delivery.response.message_handle, reply.message_handle);
  await call("getOperation", sdk.operation(project, sent.operation_ref));
  phase = "receiver_inspect_and_native_link_metadata";
  const recoveryBody = { action: "inspect", expected_revision: receiving.binding_epoch, reason: "P1 inspect current receiving capacity" };
  const recovery = await call("recoverReceiver", sdk.recoverReceiver(project, receiver, recoveryBody, "p1-receiver-inspect"));
  const recoveryAgain = await call("recoverReceiver", sdk.recoverReceiver(project, receiver, recoveryBody, "p1-receiver-inspect"));
  assert.equal(recoveryAgain.operation_id, recovery.operation_id);
  const observed = await call("getOperation", sdk.operation(project, recovery.operation_id));
  assert.equal(observed.operation_id, recovery.operation_id); assert.equal(observed.kind, "recovery");
  const linked = await call("bindNativeLink", sdk.writeNativeLink(project, "p1-native-link", nativeLink, "p1-link-write"));
  const links = await call("listNativeLinks", sdk.nativeLinks(project, { address: nativeLink.address, limit: 1 }));
  assert.deepEqual(links.items, [linked]);
  await call("listNotices", sdk.notices(project, { limit: 1 }));
  const host = createNativeWorkspaceProvider(), source = { providerRef: linked.provider_ref, sessionRef: linked.native_session_ref,
    hostRef: linked.host_ref, generation: linked.provider_generation, authority: linked.native_authority };
  assert.equal((await host.read(source)).available, false);
  assert.equal((await host.act(source, { kind: "resume" }, "unprovided-p1-host")).available, false);
  phase = "p1_checkpoint_reconnect";
  await ask("publish");
  await until(() => first.events.some(event => event.kind === "native_link.changed" && event.resource_ref === linked.link_id) &&
    first.events.some(event => event.kind === "reply.linked" && event.resource_ref === sent.message.message_handle), first, "initial_p1_facts");
  const checkpoint = first.events.at(-1).cursor;
  await stop(first);
  sends++; const late = await call("sendMessage", sdk.sendMessage(project,
    { to: peer, content: "P1 continuation message after the stream closed", activation: "message_only" }, "p1-late-message"));
  await ask("publish");
  const resumed = pump(project, checkpoint, snapshot.auth_revision);
  await until(() => resumed.events.some(event => event.kind === "message.committed" && event.resource_ref === late.message.message_handle), resumed, "p1_reconnected_message");
  await stop(resumed);
  const duplicate = pump(project, snapshot.after_cursor, snapshot.auth_revision);
  await until(() => duplicates > 0, duplicate, "p1_duplicate_replay");
  phase = "current_grant_revocation";
  await ask("revoke");
  await until(() => snapshotRequired, duplicate, "p1_revocation", { reset: true });
  await duplicate.done;
  assert.equal(state.requiresSnapshot, true); assert.equal(state.resources.size, 0); assert.equal(state.cursors.acs, null);
  const expected = ["getMeta", "getProfile", "listProjects", "listRoutes", "listContacts", "listConversations", "getConversation",
    "listMessages", "sendMessage", "readMessage", "getDelivery", "waitForMessages", "getOperation", "listReceivers", "getReceiver",
    "recoverReceiver", "getSnapshot", "subscribeEvents", "listNotices", "listNativeLinks", "bindNativeLink", "resolveConversation"];
  assert.deepEqual([...covered].sort(), expected.sort());
  const revisionUi = JSON.parse(readFileSync(new URL("../../RFC_TEMP_SOURCE/ACS-Core-Stage-Agnostic-Revision-Pack-v1.1.0/contracts/ui-scope.json", import.meta.url)));
  const originalUi = JSON.parse(readFileSync(new URL("../../RFC_TEMP_SOURCE/ACS-Core-Cross-Harness-DevPack-v1.0.0/contracts/ui-feature-matrix.json", import.meta.url)));
  const serviceUiRows = [];
  for (const row of revisionUi.features) {
    if (row.tier !== "P1_required" || row.authority === "host") continue;
    const original = originalUi.features.find(value => value.id === row.id);
    assert.ok(original, row.id);
    const methods = [...original.queries, ...original.commands].flatMap(value => value.split(","))
      .filter(value => expected.includes(value));
    // UI14's personal seen command belongs to P2; host methods are separate
    // delegate witnesses, never counted as HTTP operations or real Host support.
    assert.ok(methods.length, row.id);
    assert.ok(methods.every(value => covered.has(value)), row.id);
    serviceUiRows.push({ id: row.id, authority: row.authority, operations: methods, scope: "actual_ACS_service_operations" });
  }
  report({ type: "result", evidence: { evidence_class: "E2_local_protocol", actual_tcp: true, production_sdk: true,
    operations: [...covered].sort(), p1_operations: covered.size, p2_calls: 0, attachment_flag_enabled: false,
    explicit_peer_reply: true, timed_and_satisfied_wait: true, stable_send_key: true, send_http_requests: sends,
    recovery_original_operation: recovery.operation_id, recovery_replay_same_id: true, native_link_metadata: true,
    replay_duplicates: duplicates, revoked_cache_cleared: true, native_input_calls: 0,
    synthetic_issuer: true, controlled_native_readback: true, installed_host_qualified: false,
    real_model_qualified: false, public_ingress_qualified: false, host_read_action_grant: false,
    ui_service_rows: serviceUiRows } });
} catch (error) {
  report({ type: "failure", phase, code: typeof error.code === "string" ? error.code : error.name,
    stage: error.stage ?? null, operation: error.testOperation ?? null, effect: error.effectState ?? null,
    completed_operations: [...covered].sort(), send_http_requests: sends,
    status: Number.isInteger(error.status) ? error.status : null }); process.exitCode = 1;
} finally {
  for (const entry of [...pumps]) { entry.controller.abort(); await entry.done; }
  sdk.close(); for (const waiter of pending.values()) clearTimeout(waiter.timer);
  input.close(); process.stdin.pause();
}
