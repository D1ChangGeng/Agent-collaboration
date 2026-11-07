import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";
import { HttpCommunicationClient } from "../communication-client.ts";
import { ClientContractError } from "../client-validation.ts";

const endpoint = "https://acs.invalid/api/communication/v1/", project = "project-native", id = "native-link-one";
const address = "collaborator:project-native:slot-a";
const write = () => ({ address, receiver_ref: "receiver-one", expected_binding_epoch: 3, provider_ref: "configured-provider",
  native_session_ref: "actual-session", native_authority: "harness", expected_revision: 0,
  expected_host_ref: "actual-host", expected_provider_generation: "generation-one" });
const link = () => ({ link_id: id, project_id: project, address, receiver_ref: "receiver-one", binding_epoch: 3,
  provider_ref: "configured-provider", native_session_ref: "actual-session", native_authority: "harness",
  capabilities: ["native_session_association"], revision: 1, host_ref: "actual-host", provider_generation: "generation-one" });
const page = (items = [link()], snapshotId = null) => ({ items, page: { snapshot_id: snapshotId, next_cursor: null } });
const json = (value, init = {}) => new Response(JSON.stringify(value), { headers: { "content-type": "application/json" }, ...init });
const snapshot = (slot = "slot-a", auth = "auth-a") => ({ snapshot_id: "snapshot-one", snapshot_expires_at: "2999-01-01T00:00:00Z",
  after_cursor: "cursor-one", auth_revision: auth, actor: { address: "same-principal", principal_ref: "same-principal", level: "agent",
    agent_slot_id: slot, auth_revision: auth, allowed_actions: ["list_harnesses"] }, contacts: [], conversations: [], receivers: [], notice_count: 0,
  pages: { contacts_cursor: null, conversations_cursor: null, receivers_cursor: null } });

test("nativeLinks sends the actual address/page filters and returns all twelve metadata fields", async () => {
  let calls = 0;
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "token", fetch: async (url, options) => {
    calls++;
    assert.equal(url.pathname, "/api/communication/v1/projects/project-native/native-links");
    assert.equal(url.searchParams.get("address"), address); assert.equal(url.searchParams.get("limit"), "2");
    assert.equal(url.searchParams.get("snapshot_id"), "snapshot-A"); assert.equal(url.searchParams.get("cursor"), "opaque-page");
    assert.equal(options.method, "GET"); assert.equal(options.headers.get("Idempotency-Key"), null); assert.equal(options.headers.get("If-Match"), null);
    return json(page([link()], "snapshot-A"));
  } });
  const result = await client.nativeLinks(project, { address, limit: 2, snapshotId: "snapshot-A", cursor: "opaque-page" });
  assert.deepEqual(result.items, [link()]); assert.equal(Object.keys(result.items[0]).length, 12); assert.equal(calls, 1);
});

test("NativeLink PUT seals all nine fields before awaiting credentials and keeps revision in the body", async () => {
  let release, calls = 0, wire;
  const bearer = new Promise(resolve => { release = resolve; });
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => bearer, fetch: async (url, options) => {
    calls++; wire = JSON.parse(options.body);
    assert.equal(url.pathname, "/api/communication/v1/projects/project-native/native-links/" + id);
    assert.equal(options.method, "PUT"); assert.equal(options.headers.get("Idempotency-Key"), "exact-native-link-key");
    assert.equal(options.headers.get("If-Match"), null); assert.equal(options.headers.get("Content-Type"), "application/json");
    assert.equal(options.redirect, "error"); assert.equal(options.credentials, "omit"); return json(link());
  } });
  const body = write(), original = { ...body }, pending = client.writeNativeLink(project, id, body, "exact-native-link-key");
  body.expected_host_ref = "changed-host"; body.expected_provider_generation = "changed-generation"; body.expected_revision = 99;
  release("token");
  assert.deepEqual(await pending, link()); assert.deepEqual(wire, original); assert.equal(Object.keys(wire).length, 9); assert.equal(calls, 1);
});

for (const field of ["expected_host_ref", "expected_provider_generation"]) test("required NativeLink proof expectation cannot omit " + field, () => {
  let calls = 0;
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "token", fetch: async () => { calls++; return json(link()); } });
  const body = write(); delete body[field];
  assert.throws(() => client.writeNativeLink(project, id, body, "key"), ClientContractError); assert.equal(calls, 0);
});

test("caller Native permissions are rejected as extra write fields before any HTTP call", () => {
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "token", fetch: () => assert.fail("invalid body reached HTTP") });
  assert.throws(() => client.writeNativeLink(project, id, { ...write(), host_permissions: ["read_transcript", "submit_prompt"] }, "key"), ClientContractError);
});

for (const field of ["link_id", "project_id", "address", "receiver_ref", "binding_epoch", "provider_ref", "native_session_ref", "native_authority", "host_ref", "provider_generation"]) {
  test("successful NativeLink write result must correlate " + field, async () => {
    let calls = 0; const response = link(); response[field] = field === "binding_epoch" ? 4 : field === "native_authority" ? "orca" : "mismatched-" + field;
    const client = new HttpCommunicationClient({ endpoint, getBearer: () => "token", fetch: async () => { calls++; return json(response); } });
    await assert.rejects(client.writeNativeLink(project, id, write(), "same-key"), error => error.code === "invalid_response" && error.effectState === "unknown");
    assert.equal(calls, 1);
  });
}

for (const malformed of ["missing_host", "extra_transcript"]) test("NativeLink twelve-field DTO validation rejects " + malformed + " without resending", async () => {
  const response = link(); if (malformed === "missing_host") delete response.host_ref; else response.transcript = "PRIVATE_NATIVE_BODY";
  let calls = 0;
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "token", fetch: async () => { calls++; return json(response); } });
  await assert.rejects(client.writeNativeLink(project, id, write(), "same-key"), error => error.effectState === "unknown" && !String(error).includes("PRIVATE_NATIVE_BODY"));
  assert.equal(calls, 1);
});

for (const mismatch of ["project", "address", "snapshot"]) test("NativeLink list rejects response " + mismatch + " outside the requested scope/cut", async () => {
  const item = link(); if (mismatch === "project") item.project_id = "other-project"; if (mismatch === "address") item.address = "collaborator:project-native:other-slot";
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "token", fetch: async () => json(page([item], mismatch === "snapshot" ? "snapshot-B" : "snapshot-A")) });
  await assert.rejects(client.nativeLinks(project, { address, snapshotId: "snapshot-A" }), error => error.code === "invalid_response" && error.effectState === "none");
});

for (const reset of ["slot", "project", "auth_revision"]) test("slow NativeLink proof HTTP result cannot cross a " + reset + " context reset", async () => {
  let release, started, snapshots = 0, writes = 0;
  const gate = new Promise(resolve => { started = resolve; });
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "token", fetch: async (url) => {
    if (url.pathname.endsWith("/snapshot")) return json(snapshots++ ? snapshot(reset === "slot" ? "slot-b" : "slot-a", reset === "project" ? "auth-a" : "auth-b") : snapshot());
    writes++; started(); return new Promise(resolve => { release = resolve; });
  } });
  await client.snapshotView(project);
  const pending = client.writeNativeLink(project, id, write(), "original-key");
  await gate; await client.snapshotView(reset === "project" ? "other-project" : project); release(json(link()));
  await assert.rejects(pending, error => error.code === "authorization_changed" && error.effectState === "unknown");
  assert.equal(writes, 1);
});

test("a missing NativeLink capability stays an explicit server refusal instead of a fake empty list", async () => {
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "token", fetch: async () => json({ error: {
    code: "capability_unsupported", message: "Native links are disabled.", retryable: false, effect_state: "none", details: {} }, request_id: "opaque" }, { status: 409 }) });
  await assert.rejects(client.nativeLinks(project), error => error.code === "capability_unsupported" && error.effectState === "none");
});

test("owned loopback HTTP server checks real NativeLink list/PUT wire without conferring a Host grant", async () => {
  const calls = []; let stored = null;
  const server = createServer(async (request, response) => {
    const chunks = []; for await (const chunk of request) chunks.push(chunk);
    const url = new URL(request.url, "http://127.0.0.1");
    calls.push({ method: request.method, path: url.pathname, key: request.headers["idempotency-key"], revision: request.headers["if-match"] });
    assert.equal(request.headers.authorization, "Bearer local-protocol-token");
    let value;
    if (request.method === "PUT") {
      const body = JSON.parse(Buffer.concat(chunks).toString()); assert.deepEqual(body, write());
      stored = link(); value = stored;
    } else { assert.equal(url.searchParams.get("address"), address); value = page(stored ? [stored] : []); }
    response.writeHead(200, { "content-type": "application/json" }); response.end(JSON.stringify(value));
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const bound = server.address(), client = new HttpCommunicationClient({ endpoint: `http://127.0.0.1:${bound.port}/api/communication/v1/`, getBearer: () => "local-protocol-token" });
  try {
    assert.deepEqual((await client.nativeLinks(project, { address })).items, []);
    assert.deepEqual(await client.writeNativeLink(project, id, write(), "explicit-link-key"), link());
    assert.deepEqual((await client.nativeLinks(project, { address })).items, [link()]);
    assert.deepEqual(calls.map(call => call.method), ["GET", "PUT", "GET"]);
    assert.equal(calls[1].key, "explicit-link-key"); assert.ok(calls.every(call => call.revision === undefined));
    assert.deepEqual(stored.capabilities, ["native_session_association"]);
    assert.equal(Object.hasOwn(client, "nativeViewProvider"), false);
  } finally { client.close(); await new Promise(resolve => server.close(resolve)); }
});
