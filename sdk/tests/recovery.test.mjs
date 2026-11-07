import assert from "node:assert/strict";
import test from "node:test";
import { HttpCommunicationClient } from "../communication-client.ts";
import { CommunicationHttpError } from "../communication-http.ts";
import { ClientContractError } from "../client-validation.ts";

const endpoint = "https://acs.invalid/api/communication/v1/", project = "project", receiver = "receiver:actual/path🧭";
const timestamp = "2026-11-06T00:00:00Z";
const request = () => ({ action: "inspect", expected_revision: 4, reason: "Inspect the registered receiving capacity" });
const operation = overrides => ({ operation_id: "receiver-recovery-original", kind: "recovery", state: "completed",
  message_handle: null, receiver_ref: receiver, binding_epoch: 4, effect_state: "committed", reason_code: null,
  evidence_refs: ["command:original"], revision: 2, created_at: timestamp, updated_at: timestamp, ...overrides });
const json = (value, status = 202) => new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });

test("recovery posts the admitted body with an explicit stable key and receiver epoch, without If-Match", async () => {
  const calls = [];
  const returned = operation();
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "synthetic-bearer", fetch: async (url, init) => {
    calls.push({ url, init });
    return json(returned);
  } });
  assert.deepEqual(await client.recoverReceiver(project, receiver, request(), "original-request"), returned);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url.pathname, "/api/communication/v1/projects/project/receivers/" + encodeURIComponent(receiver) + "/actions");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers.get("Idempotency-Key"), "original-request");
  assert.equal(calls[0].init.headers.get("If-Match"), null);
  assert.equal(calls[0].init.headers.get("Content-Type"), "application/json");
  assert.equal(calls[0].init.redirect, "error");
  assert.equal(calls[0].init.credentials, "omit");
  assert.deepEqual(JSON.parse(calls[0].init.body), request());
  assert.equal("nativeState" in returned, false);
});

for (const body of [
  { ...request(), actor_ref: "untrusted" }, { ...request(), expected_revision: true },
  { ...request(), reason: " \n\t" }, { ...request(), action: "arbitrary_host_control" },
  { action: "reconcile", expected_revision: 4, reason: "Reconcile" },
  { action: "retry_delivery", expected_revision: 4, reason: "Retry" },
  { action: "rebind_receiver", expected_revision: 4, reason: "Rebind" },
]) test("invalid recovery identity, action scope or required fields fail before credential/network access: " + JSON.stringify(body), () => {
  const client = new HttpCommunicationClient({ endpoint,
    getBearer: () => assert.fail("Invalid request acquired credentials"), fetch: async () => assert.fail("Invalid request made a request") });
  assert.throws(() => client.recoverReceiver(project, receiver, body, "key"), ClientContractError);
});

test("reconcile and rebind retain their explicit original operation or target reference", async () => {
  const bodies = [];
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "synthetic", fetch: async (_url, init) => {
    bodies.push(JSON.parse(init.body)); return json(operation({ state: "definitively_rejected", reason_code: "host_extension_required" }));
  } });
  await client.recoverReceiver(project, receiver, { ...request(), action: "reconcile", operation_ref: "original-delivery" }, "reconcile-key");
  await client.recoverReceiver(project, receiver, { ...request(), action: "rebind_receiver", target_endpoint_ref: "explicit-replacement" }, "rebind-key");
  assert.equal(bodies[0].operation_ref, "original-delivery");
  assert.equal(bodies[1].target_endpoint_ref, "explicit-replacement");
});

for (const fault of [{ receiver_ref: "another-receiver" }, { binding_epoch: 5 }, { binding_epoch: null }, { kind: "send" }]) {
  test("another receiver, epoch or operation kind is an unknown write outcome: " + JSON.stringify(fault), async () => {
    let calls = 0;
    const client = new HttpCommunicationClient({ endpoint, getBearer: () => "synthetic", fetch: async () => {
      calls++; return json(operation(fault));
    } });
    await assert.rejects(client.recoverReceiver(project, receiver, request(), "original-key"),
      error => error instanceof CommunicationHttpError && error.code === "invalid_response" && error.effectState === "unknown");
    assert.equal(calls, 1);
  });
}

test("recovery captures mutable request fields before asynchronous bearer acquisition", async () => {
  let release, entered;
  const ready = new Promise(resolve => { entered = resolve; });
  const gate = new Promise(resolve => { release = resolve; });
  let sent;
  const client = new HttpCommunicationClient({ endpoint, getBearer: async () => { entered(); await gate; return "synthetic"; },
    fetch: async (_url, init) => { sent = JSON.parse(init.body); return json(operation()); } });
  const mutable = request();
  const pending = client.recoverReceiver(project, receiver, mutable, "key");
  await ready;
  mutable.expected_revision = 99; mutable.reason = "Changed after request began"; mutable.action = "clear";
  release();
  await pending;
  assert.deepEqual(sent, request());
});

test("lost response never silently retries a recovery command", async () => {
  let calls = 0;
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "synthetic", fetch: async () => {
    calls++; throw new TypeError("Controlled connection loss after submission");
  } });
  await assert.rejects(client.recoverReceiver(project, receiver, request(), "same-key"),
    error => error.code === "network_error" && error.effectState === "unknown");
  assert.equal(calls, 1);
});

test("a committed server problem retains its original operation for explicit caller recovery", async () => {
  let calls = 0;
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "synthetic", fetch: async () => {
    calls++;
    return json({ request_id: "request-original", error: { code: "observation_unavailable", message: "Observe the original operation",
      retryable: false, effect_state: "committed", operation_ref: "receiver-recovery-original", details: {} } }, 503);
  } });
  await assert.rejects(client.recoverReceiver(project, receiver, request(), "same-key"), error =>
    error.code === "observation_unavailable" && error.operationRef === "receiver-recovery-original" &&
    error.effectState === "committed" && !error.retryable);
  assert.equal(calls, 1);
});

test("a current scope refusal remains403 with no effect and no automatic retry", async () => {
  let calls = 0;
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "synthetic", fetch: async () => {
    calls++;
    return json({ request_id: "scope-refusal", error: { code: "authorization_denied", message: "Required scope unavailable",
      retryable: false, effect_state: "none", details: {} } }, 403);
  } });
  await assert.rejects(client.recoverReceiver(project, receiver, { ...request(), action: "prepare_receiver" }, "same-key"), error =>
    error.status === 403 && error.code === "authorization_denied" && error.effectState === "none" && !error.retryable);
  assert.equal(calls, 1);
});

test("closing the caller context rejects a late recovery result with conservative write effect", async () => {
  let release, entered;
  const ready = new Promise(resolve => { entered = resolve; });
  const client = new HttpCommunicationClient({ endpoint, getBearer: () => "synthetic", fetch: async () => {
    entered(); return new Promise(resolve => { release = resolve; });
  } });
  const pending = client.recoverReceiver(project, receiver, request(), "same-key");
  await ready; client.close(); release(json(operation()));
  await assert.rejects(pending, error => error.code === "authorization_changed" && error.effectState === "unknown");
});
