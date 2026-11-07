// Test consumer: production SDK, real loopback fetch, actual Core responses.
import assert from "node:assert/strict";
import { createInterface } from "node:readline";
import { HttpCommunicationClient } from "../communication-client.ts";
import { createNativeWorkspaceProvider } from "../integration-ports.ts";

const base = process.env.ACS_NATIVE_LINK_TEST_URL;
const bearer = process.env.ACS_NATIVE_LINK_TEST_BEARER;
if (!base || !bearer || new URL(base).hostname !== "127.0.0.1") throw new Error("Owned loopback configuration required");
const lines = createInterface({ input: process.stdin });
const pending = new Map();
let initial, sequence = 0, phase = "configuration", puts = 0, gets = 0;
const configuration = new Promise(resolve => { initial = resolve; });
const report = value => process.stdout.write(JSON.stringify(value) + "\n");
lines.on("line", line => {
  const value = JSON.parse(line);
  if (value.type === "configuration") { initial(value); return; }
  const waiter = pending.get(value.id);
  if (waiter) { pending.delete(value.id); clearTimeout(waiter.timer); waiter.resolve(value.result); }
});
function ask(action) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error("Fixture coordination deadline")); }, 20000);
    pending.set(id, { resolve, reject, timer }); report({ type: "request", id, action });
  });
}
const fields = ["address", "receiver_ref", "expected_binding_epoch", "provider_ref", "native_session_ref",
  "native_authority", "expected_revision", "expected_host_ref", "expected_provider_generation"].sort();
const fetcher = async (url, init) => {
  if (new URL(url).pathname.includes("/native-links")) {
    if (init.method === "PUT") {
      puts++;
      assert.deepEqual(Object.keys(JSON.parse(init.body)).sort(), fields);
      assert.ok(init.headers.get("Idempotency-Key"));
      assert.equal(init.headers.get("If-Match"), null);
    } else gets++;
  }
  return fetch(url, init);
};
const client = new HttpCommunicationClient({ endpoint: new URL("/api/communication/v1/", base), getBearer: () => bearer, fetch: fetcher });
try {
  const { project, body, quotas } = await configuration; // Outbound request inputs from the configured existing source, never response DTOs.
  phase = "metadata_handshake";
  const meta = await client.meta();
  assert.ok(meta.features.includes("native_links"));
  for (const [key, value] of Object.entries(quotas)) assert.equal(meta.limits[key], value);
  const snapshot = await client.snapshotView(project, { limit: 1 });
  phase = "actual_sdk_writes";
  const ids = ["sdk-native-main", "sdk-native-汉字🧭", "sdk-native-third"];
  const keys = ["request-sdk-native-main", "request-sdk-native-unicode", "request-sdk-native-third"];
  const originals = [];
  for (const [index, id] of ids.entries()) {
    const result = await client.writeNativeLink(project, id, body, keys[index]);
    assert.equal(Object.keys(result).length, 12);
    assert.equal(result.link_id, id); assert.equal(result.project_id, project);
    assert.equal(result.host_ref, body.expected_host_ref); assert.equal(result.provider_generation, body.expected_provider_generation);
    assert.equal(result.revision, 1); originals.push(result);
  }
  assert.deepEqual(await client.writeNativeLink(project, ids[0], body, keys[0]), originals[0]);
  phase = "frozen_metadata_pages";
  let page = await client.nativeLinks(project, { limit: 1, address: body.address });
  const snapshotId = page.page.snapshot_id, seen = new Set(page.items.map(item => item.link_id));
  let pages = 1;
  while (page.page.next_cursor) {
    page = await client.nativeLinks(project, { limit: 1, address: body.address, snapshotId, cursor: page.page.next_cursor });
    assert.equal(page.page.snapshot_id, snapshotId);
    for (const item of page.items) { assert.equal(seen.has(item.link_id), false); seen.add(item.link_id); }
    assert.ok(++pages <= 3);
  }
  assert.deepEqual([...seen].sort(), [...ids].sort());
  phase = "actual_projection_events";
  await ask("publish");
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
  const events = [];
  try {
    for await (const event of client.events(project, snapshot.after_cursor,
      { signal: controller.signal, kinds: ["native_link.changed"] })) {
      assert.equal(event.kind, "native_link.changed"); assert.deepEqual(event.payload, {});
      assert.equal(event.resource_revision, 1); assert.ok(ids.includes(event.resource_ref));
      events.push(event);
      if (new Set(events.map(item => item.resource_ref)).size === ids.length) break;
    }
  } finally { clearTimeout(timer); controller.abort(); }
  assert.equal(new Set(events.map(item => item.resource_ref)).size, 3);
  phase = "separate_host_authority";
  const native = createNativeWorkspaceProvider();
  const source = { providerRef: originals[0].provider_ref, sessionRef: originals[0].native_session_ref,
    hostRef: originals[0].host_ref, generation: originals[0].provider_generation, authority: originals[0].native_authority };
  assert.equal((await native.read(source)).available, false);
  assert.equal((await native.act(source, { kind: "resume" }, "unprovided-host-action")).available, false);
  phase = "real_endpoint_reassignment";
  await ask("reassign");
  assert.deepEqual(await client.writeNativeLink(project, ids[0], body, keys[0]), originals[0]);
  await assert.rejects(client.writeNativeLink(project, ids[0], body, "fresh-after-reassignment"),
    error => [403, 404, 409].includes(error.status) && error.effectState === "none");
  const retained = await client.nativeLinks(project, { address: body.address });
  assert.deepEqual(retained.items.find(item => item.link_id === ids[0]), originals[0]);
  report({ type: "result", evidence: { real_tcp: true, production_sdk: true, synthetic_issuer: true,
    controlled_existing_native_readback: true, live_host_qualified: false, model_qualified: false,
    declared_request_fields: 9, returned_fields: 12, actual_quotas: true, stable_snapshot_pages: pages,
    native_link_events: events.length, original_outcome_after_scope_slot_reassignment: true,
    host_read_action_permission_granted: false, native_inputs: 0, writes_attempted: puts, metadata_gets: gets } });
} catch (error) {
  report({ type: "failure", phase, code: typeof error.code === "string" ? error.code : error.name,
    status: Number.isInteger(error.status) ? error.status : null }); process.exitCode = 1;
} finally {
  client.close(); for (const waiting of pending.values()) clearTimeout(waiting.timer);
  lines.close(); process.stdin.pause();
}
