import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import test from "node:test";
import { HttpCommunicationClient } from "../communication-client.ts";
import { CommunicationHttpError } from "../communication-http.ts";
import { ClientContractError, validateClientModel } from "../client-validation.ts";

const endpoint = "https://acs.invalid/api/communication/v1/", project = "project", handle = "message:project:one";
const timestamp = "2026-11-06T00:00:00Z", conversation = "conversation-one", peer = "collaborator:project:b";
const hash = data => createHash("sha256").update(data).digest("hex");
const json = (value, init = {}) => new Response(JSON.stringify(value), { headers: { "content-type": "application/json" }, ...init });
const actor = (slot = "slot-a", principal = "agent:a", revision = "auth-a") => ({ address: principal, principal_ref: principal,
  level: "agent", agent_slot_id: slot, auth_revision: revision, allowed_actions: ["read_message", "send_message"] });
const snapshot = (slot, principal, revision = "auth-a") => ({ snapshot_id: "snapshot-one", snapshot_expires_at: "2999-01-01T00:00:00Z",
  after_cursor: "cursor-one", auth_revision: revision, actor: actor(slot, principal, revision), contacts: [], conversations: [], receivers: [], notice_count: 0,
  pages: { contacts_cursor: null, conversations_cursor: null, receivers_cursor: null } });
const page = { items: [], page: { next_cursor: null, snapshot_id: null } };
function message(text = "Full body 🧭", overrides = {}) {
  return { message_handle: handle, project_id: project, conversation_id: conversation, sender: "collaborator:project:a", to: peer,
    content: { text, offset: 0, next_offset: null, total_bytes: Buffer.byteLength(text), digest: hash(text) },
    reply_to: [], attachment_refs: [], conversation_sequence: "1", committed_at: timestamp, revision: 1, source: "acs_agent", first_reply_handle: null, ...overrides };
}
const read = current => ({ message: current, first_reply: null, continuations: [] });
function delivery() {
  return { message_handle: handle, accepted_by_authority: true, target_inbox_committed: true,
    native: { state: "not_requested", operation_ref: null, binding_epoch: null, provider_generation: null, evidence_ref: null, native_input_ref: null, reason_code: null },
    consumption: { state: "unobservable", semantics: "provider_input_consumed", evidence_ref: null }, response: { present: false, message_handle: null }, revision: 1 };
}
function sent() { return { message: message(), delivery: delivery(), operation_ref: "operation-one", duplicate: false,
  wait: { state: "not_requested", satisfied_handles: [], pending_handles: [] } }; }
const preferences = { archived: false, muted: true, revision: 1 };
const draft = { content: "Unsent", attachment_refs: [], revision: 1, updated_at: timestamp };
const readState = { conversation_id: conversation, through_message_handle: handle, unread_override: false, revision: 1 };
const convo = { conversation_id: conversation, project_id: project, participants: ["collaborator:project:a", peer], last_message_handle: null,
  last_activity_at: null, unread_count: 0, revision: 1, archived: false, muted: false };
const notice = { notice_handle: "notice-opaque", source: "acs_system", kind: "delivery_failed", message_ref: null, receiver_ref: null,
  reason_code: "fixture-refusal", summary: "Technical status", own_delivery: null, seen: true, revision: 1, created_at: timestamp };
const receiver = { receiver_id: "receiver:one/path", address: peer, binding_epoch: 1, revision: 1, native_session_ref: null,
  capability_scope: { adapter_id: "fixture", adapter_version: "1", harness_kind: "unknown", harness_version: null, execution_host_ref: "host", binary_digest: null,
    config_digest: null, connection_epoch: 1, provider_generation: null }, capabilities: [], observations: [], allowed_actions: ["inspect"] };
const operation = { operation_id: "operation-one", kind: "send", state: "queued", message_handle: handle, receiver_ref: null, binding_epoch: null,
  effect_state: "committed", reason_code: null, evidence_refs: [], revision: 1, created_at: timestamp, updated_at: timestamp };
const assetBytes = Buffer.from("附件 🧭"), asset = { attachment_id: "attachment-opaque", project_id: project, name: "附件.txt", media_type: "text/plain",
  bytes: assetBytes.length, sha256: hash(assetBytes), state: "reserved", upload_path: null, expires_at: "2999-01-01T00:00:00Z", revision: 1 };
const meta = { schema_version: "acs-client/1", server_version: "2.3.1", authority_id: "authority", authority_incarnation: "incarnation", features: ["attachments", "events"],
  limits: { message_bytes: 262144, page_items: 100, attachment_bytes: 20971520, attachment_count: 8, attachment_total_bytes: 52428800,
    attachment_staging_bytes: 104857600, attachment_project_staging_bytes: 1073741824, attachment_staging_seconds: 86400, event_replay_seconds: 604800,
    native_link_count: 0, native_link_history_revisions: 0, native_link_write_receipts: 0, native_link_metadata_bytes: 0 },
  adapter_protocol: "acs-adapter/1", event_protocol: "acs-event/1" };

test("optional original Native source queries preserve separate provenance and reject another message", async () => {
  const calls = [];
  let wrong = false, unavailable = false;
  const source = { messageHandle: handle, operationId: "original-operation", bindingEpoch: 7,
    nativeTurnRef: "original-turn", nativeSession: { providerRef: "server-provider", sessionRef: "original-session",
      hostRef: "original-host", generation: "original-generation", authority: "harness" } };
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async url => {
    calls.push(url.searchParams.get("include_native_source"));
    const body = read(message());
    if (url.searchParams.get("include_native_source") === "true") body.native_source = unavailable
      ? { available: false, value: null, reason_code: "native_source_provider_unavailable", evidence_ref: null }
      : { available: true, value: { ...source, messageHandle: wrong ? "message:project:other" : handle }, reason_code: null, evidence_ref: "driver-source:proof" };
    return json(body);
  } });
  try {
    assert.equal((await client.readMessage(project, handle)).native_source, undefined);
    assert.equal((await client.readMessage(project, handle, { includeNativeSource: false })).native_source, undefined);
    assert.deepEqual((await client.readMessage(project, handle, { includeNativeSource: true })).native_source.value, source);
    unavailable = true;
    assert.equal((await client.readMessage(project, handle, { includeNativeSource: true })).native_source.available, false);
    unavailable = false; wrong = true;
    await assert.rejects(client.readMessage(project, handle, { includeNativeSource: true }), error => error.code === "invalid_response" && error.effectState === "none");
    assert.deepEqual(calls, [null, null, "true", "true", "true"]);
    assert.throws(() => client.readMessage(project, handle, { includeNativeSource: "true" }), TypeError);
  } finally { client.close(); }
});

test("all existing REST method families use owned paths, current DTOs, explicit keys and the right CAS headers", async () => {
  const calls = [];
  const fetch = async (url, options) => {
    calls.push({ path: url.pathname, query: url.searchParams, options });
    const path = decodeURIComponent(url.pathname), method = options.method;
    if (path.endsWith("/meta")) return json(meta);
    if (path.endsWith("/profile")) return json(actor());
    if (path.endsWith("/snapshot")) return json(snapshot());
    if (path.endsWith("/resolve") || path.endsWith("/conversations/" + conversation)) return json(convo);
    if (path.endsWith("/delivery")) return json(delivery());
    if (path.includes("/messages/")) return json(read(message()));
    if (path.endsWith("/messages") && method === "POST") return json(sent());
    if (path.endsWith("/seen")) return json(notice);
    if (path.endsWith("/read-state")) return json(readState);
    if (path.endsWith("/preferences")) return json(preferences);
    if (path.endsWith("/draft")) return json(draft);
    if (path.endsWith("/waits")) return json({ wait: { state: "not_requested", satisfied_handles: [], pending_handles: [] }, items: [], continuations: [] });
    if (path.includes("/operations/")) return json(operation);
    if (path.includes("/receivers/")) return json(receiver);
    return json(page);
  };
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "valid-token", fetch });
  await client.meta(); await client.profile(); await client.projects({ limit: 2, cursor: "opaque" }); await client.routes(project);
  await client.contacts(project, { name: "汉字", scopeHandle: "scope:project:own" });
  await client.conversations(project, { includeArchived: true }); await client.resolveConversation(project, peer); await client.conversation(project, conversation);
  await client.messages(project, { peer, conversationId: conversation, replyRoot: handle, direction: "incoming" });
  await client.readMessage(project, handle); await client.delivery(project, handle); await client.search(project, "query");
  await client.snapshotView(project); await client.receivers(project); await client.receiver(project, receiver.receiver_id); await client.notices(project);
  const write = { requestId: "exact-key", expectedRevision: "0" };
  await client.markSeen(project, notice.notice_handle, { seen: true }, write);
  await client.readState(project, conversation); await client.markRead(project, conversation, { through_message_handle: handle }, write);
  await client.preferences(project, conversation); await client.updatePreferences(project, conversation, { muted: true }, write);
  await client.draft(project, conversation); await client.updateDraft(project, conversation, { content: "Unsent", attachment_refs: [] }, write);
  await client.deleteDraft(project, conversation, write); await client.wait(project, { handles: [handle], timeout_seconds: 0 });
  await client.operation(project, "operation-one"); await client.sendMessage(project, { to: peer, content: "Explicit send" }, "send-key");
  assert.equal(calls.length, 27);
  for (const call of calls) {
    assert.equal(call.options.redirect, "error"); assert.equal(call.options.credentials, "omit");
    assert.equal(call.options.headers.get("Authorization"), "Bearer valid-token");
    if (["PUT", "DELETE"].includes(call.options.method)) {
      assert.equal(call.options.headers.get("Idempotency-Key"), "exact-key"); assert.equal(call.options.headers.get("If-Match"), '"0"');
    }
  }
  assert.equal(calls.at(-1).options.headers.get("If-Match"), null);
  assert.equal(calls.at(-1).options.headers.get("Idempotency-Key"), "send-key");
  assert.ok(calls.some(call => call.path.includes("receiver%3Aone%2Fpath")));
  assert.ok(calls.some(call => call.query.get("with") === peer));
});

test("mutable send body and options cannot alter an in-flight idempotent intent", async () => {
  let release, body;
  const credentials = new Promise(resolve => { release = resolve; });
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => credentials, fetch: async (_url, options) => { body = options.body; return json(sent()); } });
  const request = { to: peer, content: "Original text", reply_to: [] };
  const result = client.sendMessage(project, request, "unchanged-key");
  request.content = "Changed after await"; request.reply_to.push("forged-reply"); release("valid"); await result;
  assert.deepEqual(JSON.parse(body), { to: peer, content: "Original text", reply_to: [] });
});

test("complete message uses UTF-8 byte boundaries and verifies the complete immutable digest", async () => {
  const text = "汉字🧭tail", bytes = Buffer.from(text), pieces = [Buffer.from("汉字"), Buffer.from("🧭tail")]; let calls = 0;
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async (url) => {
    const index = calls++, offset = Number(url.searchParams.get("offset"));
    assert.equal(offset, index === 0 ? 0 : pieces[0].length);
    return json(read(message(text, { content: { text: pieces[index].toString(), offset, next_offset: index === 0 ? pieces[0].length : null, total_bytes: bytes.length, digest: hash(bytes) } })));
  } });
  const complete = await client.readMessageComplete(project, handle, { maxInlineBytes: 8, maxBytes: 128 });
  assert.equal(complete.text, text); assert.deepEqual(Buffer.from(complete.bytes), bytes); assert.equal(calls, 2);
});

for (const fault of ["digest", "total", "progress", "identity", "budget", "pages"]) test("complete body fails closed on " + fault, async () => {
  let count = 0;
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async () => {
    const first = count++ === 0;
    const body = { text: first ? "a" : "b", offset: first ? 0 : 1, next_offset: first ? 1 : null, total_bytes: 2, digest: hash("ab") };
    if (fault === "digest") body.digest = "0".repeat(64);
    if (fault === "total" && !first) body.total_bytes = 3;
    if (fault === "progress") body.next_offset = 0;
    return json(read(message("ab", { message_handle: fault === "identity" ? "message:project:wrong" : handle, content: body })));
  } });
  await assert.rejects(client.readMessageComplete(project, handle, { maxBytes: fault === "budget" ? 1 : 64, maxPages: fault === "pages" ? 1 : 8 }));
  assert.ok(count <= 2);
});

test("attachment PUT is one explicit operation with sealed Buffer bytes, no hidden reserve/finalize or If-Match", async () => {
  let release, request;
  const bearer = new Promise(resolve => { release = resolve; });
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => bearer, fetch: async (url, options) => {
    request = { url, options }; return json({ ...asset, state: "uploaded", revision: 3 });
  } });
  const input = Buffer.from(assetBytes), declaration = { ...asset };
  const result = client.uploadAttachment(project, declaration, input, "upload-original");
  input.fill(0); declaration.sha256 = "0".repeat(64); declaration.attachment_id = "different";
  release("valid"); const uploaded = await result;
  assert.equal(uploaded.state, "uploaded"); assert.equal(request.options.method, "PUT");
  assert.ok(request.url.pathname.endsWith("/attachments/attachment-opaque/content"));
  assert.equal(request.options.headers.get("Content-Type"), "application/octet-stream");
  assert.equal(request.options.headers.get("If-Match"), null); assert.equal(request.options.headers.get("Idempotency-Key"), "upload-original");
  assert.deepEqual(Buffer.from(request.options.body), assetBytes);
});

test("attachment download requires all bytes and exact media/ETag/digest before exposing content", async () => {
  for (const corrupt of [false, true]) {
    const client = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async () => new Response(corrupt ? Buffer.alloc(asset.bytes) : assetBytes,
      { headers: { "content-type": asset.media_type, "content-length": String(asset.bytes), etag: '"' + asset.sha256 + '"' } }) });
    if (corrupt) await assert.rejects(client.downloadAttachment(project, { ...asset, state: "ready" }));
    else assert.deepEqual(Buffer.from((await client.downloadAttachment(project, { ...asset, state: "ready" })).bytes), assetBytes);
  }
});

test("owner-changing snapshot fences prior in-flight reads and pending writes instead of publishing them to the new actor", async () => {
  let snapshotNumber = 0, release, started;
  const gate = new Promise(resolve => { started = resolve; });
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async (url) => {
    if (url.pathname.endsWith("/snapshot")) return json(snapshotNumber++ ? snapshot("slot-b", "agent:a", "auth-b") : snapshot("slot-a", "agent:a", "auth-a"));
    started(); return new Promise(resolve => { release = resolve; });
  } });
  await client.snapshotView(project);
  const pending = client.sendMessage(project, { to: peer, content: "Old actor pending intent" }, "original-key");
  await gate; const current = await client.snapshotView(project); release(json(sent()));
  assert.equal(current.actor.agent_slot_id, "slot-b");
  await assert.rejects(pending, error => error instanceof CommunicationHttpError && error.effectState === "unknown" && error.code === "authorization_changed");
});

for (const composite of ["complete_read", "upload"]) for (const reset of ["slot", "project", "auth_revision", "auth_loss", "close"]) test(reset + " reset during asynchronous digest fences the whole " + composite + " operation", async () => {
  let snapshotNumber = 0, release, entered, writes = 0;
  const enteredDigest = new Promise(resolve => { entered = resolve; }), continueDigest = new Promise(resolve => { release = resolve; });
  const subtle = globalThis.crypto.subtle, original = subtle.digest.bind(subtle), descriptor = Object.getOwnPropertyDescriptor(subtle, "digest");
  Object.defineProperty(subtle, "digest", { configurable: true, value: async (...args) => { entered(); await continueDigest; return original(...args); } });
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async (url, options) => {
    if (url.pathname.endsWith("/snapshot")) return json(snapshotNumber++ ? snapshot(reset === "slot" ? "slot-b" : "slot-a", "agent:a", reset === "project" ? "auth-a" : "auth-b") : snapshot("slot-a", "agent:a", "auth-a"));
    if (url.pathname.endsWith("/profile")) return json({ error: { code: "unauthenticated", message: "Expired", retryable: false, effect_state: "none", details: {} }, request_id: "opaque-request" }, { status: 401 });
    if (options.method !== "GET") { writes++; return json({ ...asset, state: "uploaded", revision: 3 }); }
    return json(read(message("PRIVATE_A")));
  } });
  try {
    await client.snapshotView(project);
    const pending = composite === "complete_read" ? client.readMessageComplete(project, handle) : client.uploadAttachment(project, asset, assetBytes, "old-owner-key");
    await enteredDigest;
    if (reset === "close") client.close();
    else if (reset === "auth_loss") await assert.rejects(client.profile(), error => error.requiresSnapshot);
    else {
      const current = await client.snapshotView(reset === "project" ? "other-project" : project);
      assert.equal(current.actor.agent_slot_id, reset === "slot" ? "slot-b" : "slot-a");
    }
    release();
    await assert.rejects(pending, error => error.code === "authorization_changed" && error.effectState === "none");
    assert.equal(writes, 0);
  } finally {
    release();
    if (descriptor) Object.defineProperty(subtle, "digest", descriptor); else delete subtle.digest;
    client.close();
  }
});

test("delivery and SendResponse cannot attach another message's Native facts to the requested message", async () => {
  const unrelated = { ...delivery(), message_handle: "message:project:other", native: { ...delivery().native, state: "accepted", operation_ref: "other-native-operation", evidence_ref: "other-evidence" } };
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async (url) => json(url.pathname.endsWith("/delivery") ? unrelated : { ...sent(), delivery: unrelated }) });
  await assert.rejects(client.delivery(project, handle), error => error.code === "invalid_response" && error.effectState === "none");
  await assert.rejects(client.asPort().send(project, { to: peer, content: "x" }, "key"), error => error.code === "invalid_response" && error.effectState === "unknown");
});

test("frozen pages must match the explicitly requested snapshot and preserve it through pagination", async () => {
  let calls = 0;
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async url => {
    calls++; assert.equal(url.searchParams.get("snapshot_id"), "snapshot-A");
    return json({ items: [], page: { snapshot_id: calls === 3 ? "snapshot-B" : "snapshot-A", next_cursor: calls === 1 ? "next-opaque" : null } });
  } });
  const first = await client.contacts(project, { snapshotId: "snapshot-A" });
  await client.contacts(project, { snapshotId: first.page.snapshot_id, cursor: first.page.next_cursor });
  await assert.rejects(client.contacts(project, { snapshotId: "snapshot-A", cursor: "next-opaque" }), error => error.code === "invalid_response");
  assert.equal(calls, 3);
});

test("a completed PUT cannot change immutable reservation name or MIME", async () => {
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async () => json({ ...asset, state: "uploaded", revision: 3, name: "changed-name", media_type: "application/json" }) });
  await assert.rejects(client.uploadAttachment(project, asset, assetBytes, "key"), error => error.code === "invalid_response" && error.effectState === "unknown");
});

test("integration port maps actual receipt facts without turning Native status into an explicit reply", async () => {
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async (url) => {
    if (url.pathname.endsWith("/snapshot")) return json(snapshot());
    if (url.pathname.endsWith("/messages")) return json(sent());
    return json(read(message()));
  } });
  const port = client.asPort();
  const receipt = await port.send(project, { to: peer, content: "Communication only" }, "port-key");
  assert.equal(receipt.messageHandle, handle); assert.equal(receipt.nativeState, "not_requested"); assert.equal(receipt.explicitReplyHandle, null);
  const captured = await port.snapshot(project); assert.equal(captured.snapshotId, "snapshot-one");
  const actual = await port.readMessage(project, handle); assert.equal(actual.message.message_handle, handle);
});

test("SSE adapter reuses the production parser, fetch injection, exact cursor pair and snapshot auth fence", async () => {
  const event = { schema_version: "acs-event/1", event_id: "event-one", cursor: "cursor-next", project_id: project,
    kind: "attachment.ready", resource_ref: asset.attachment_id, resource_revision: 4, committed_at: timestamp, auth_revision: "auth-a", payload: {} };
  let calls = 0;
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async (url, options) => {
    calls++;
    if (url.pathname.endsWith("/snapshot")) return json(snapshot());
    assert.equal(url.searchParams.get("after_cursor"), "cursor-one"); assert.equal(options.headers.get("Last-Event-ID"), "cursor-one");
    assert.deepEqual(url.searchParams.getAll("kinds"), ["attachment.ready"]);
    return new Response(`id: cursor-next\nevent: attachment.ready\ndata: ${JSON.stringify(event)}\n\n`, { headers: { "content-type": "text/event-stream" } });
  } });
  await assert.rejects(client.events(project, "cursor-one").next(), error => error.requiresSnapshot);
  assert.equal(calls, 0);
  await client.snapshotView(project);
  const observed = [];
  for await (const value of client.events(project, "cursor-one", { kinds: ["attachment.ready"] })) observed.push(value);
  assert.deepEqual(observed, [event]); assert.equal(calls, 2);
});

test("wrong-project successful write DTO remains unknown, while snapshot identity mismatch is rejected", async () => {
  const write = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async () => json({ ...sent(), message: message("x", { project_id: "another-project" }) }) });
  await assert.rejects(write.sendMessage(project, { to: peer, content: "x" }, "key"), error => error.code === "invalid_response" && error.effectState === "unknown");
  const read = new HttpCommunicationClient({ endpoint, getBearer: () => "valid", fetch: async () => json({ ...snapshot(), auth_revision: "mismatched-auth" }) });
  await assert.rejects(read.snapshotView(project), error => error.code === "invalid_response" && error.effectState === "none");
});

test("owned local HTTP protocol server exercises reserve/PUT/finalize/download through real fetch", async () => {
  // This server checks the SDK transport protocol, not ACS authorization or a Native host.
  let state = "reserved", bytes = null; const calls = [];
  const server = createServer(async (request, response) => {
    const chunks = []; for await (const chunk of request) chunks.push(chunk); const body = Buffer.concat(chunks);
    calls.push({ method: request.method, path: request.url, key: request.headers["idempotency-key"], ifMatch: request.headers["if-match"] });
    assert.equal(request.headers.authorization, "Bearer owned-local-token");
    const path = request.url.split("?", 1)[0];
    if (request.method === "POST" && path.endsWith("/attachments")) {
      const declared = JSON.parse(body.toString()); validateClientModel("AttachmentCreate", declared);
    } else if (request.method === "PUT") { bytes = body; state = "uploaded"; assert.equal(request.headers["content-type"], "application/octet-stream"); }
    else if (request.method === "POST" && path.endsWith("/finalize")) { assert.equal(state, "uploaded"); state = "ready"; }
    else if (request.method === "GET" && path.endsWith("/content")) {
      response.writeHead(200, { "content-type": asset.media_type, "content-length": bytes.length, etag: '"' + asset.sha256 + '"' }); response.end(bytes); return;
    }
    response.writeHead(200, { "content-type": "application/json" }); response.end(JSON.stringify({ ...asset, state, revision: state === "ready" ? 4 : state === "uploaded" ? 3 : 1 }));
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  const client = new HttpCommunicationClient({ endpoint: `http://127.0.0.1:${address.port}/api/communication/v1/`, getBearer: () => "owned-local-token" });
  try {
    const reservation = await client.reserveAttachment(project, { name: asset.name, media_type: asset.media_type, bytes: asset.bytes, sha256: asset.sha256 }, "reserve-key");
    await client.uploadAttachment(project, reservation, assetBytes, "upload-key");
    const finalized = await client.finalizeAttachment(project, reservation.attachment_id, { bytes: asset.bytes, sha256: asset.sha256 }, "finalize-key");
    assert.deepEqual(Buffer.from((await client.downloadAttachment(project, finalized)).bytes), assetBytes);
    assert.deepEqual(calls.map(call => call.method), ["POST", "PUT", "POST", "GET"]);
    assert.deepEqual(calls.slice(0, 3).map(call => call.key), ["reserve-key", "upload-key", "finalize-key"]);
    assert.ok(calls.every(call => call.ifMatch === undefined));
  } finally { client.close(); await new Promise(resolve => server.close(resolve)); }
});

test("owned local body server enforces the UTF-8 codepoint boundary without client truncation or automatic retry", async () => {
  const text = "🧭", calls = [];
  const server = createServer((request, response) => {
    const url = new URL(request.url, "http://127.0.0.1"); calls.push(Number(url.searchParams.get("max_inline_bytes")));
    if (Number(url.searchParams.get("max_inline_bytes")) < Buffer.byteLength(text)) {
      response.writeHead(400, { "content-type": "application/problem+json" });
      response.end(JSON.stringify({ error: { code: "invalid_argument", message: "Next UTF-8 character exceeds the byte budget.", retryable: false, effect_state: "none", details: {} }, request_id: "opaque-utf8-request" }));
      return;
    }
    response.writeHead(200, { "content-type": "application/json" }); response.end(JSON.stringify(read(message(text))));
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address(), client = new HttpCommunicationClient({ endpoint: `http://127.0.0.1:${address.port}/api/communication/v1/`, getBearer: () => "valid" });
  try {
    await assert.rejects(client.readMessageComplete(project, handle, { maxInlineBytes: 3 }), error => error.code === "invalid_argument" && error.effectState === "none");
    assert.deepEqual(calls, [3]);
    assert.equal((await client.readMessageComplete(project, handle, { maxInlineBytes: 4 })).text, text);
    assert.deepEqual(calls, [3, 4]);
  } finally { client.close(); await new Promise(resolve => server.close(resolve)); }
});
