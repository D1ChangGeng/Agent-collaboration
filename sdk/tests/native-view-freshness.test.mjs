import assert from "node:assert/strict";
import test from "node:test";
import { createNativeWorkspaceProvider, invalidateNativeState, PortOperationUnavailable } from "../integration-ports.ts";

const session = Object.freeze({ providerRef: "provider", hostRef: "host", sessionRef: "session", generation: "generation", authority: "harness" });
const allow = () => ({ available: true, value: undefined });
const denied = { available: false, code: "unauthorized", reason: "Current Host grant revoked" };
const available = value => ({ available: true, value });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };

for (const operation of ["capabilities", "read", "state", "readResource"]) {
  test(`${operation} cannot release Host data after revocation during its delegate`, async () => {
    let authorized = true, calls = 0;
    const entered = deferred(), finish = deferred();
    const provider = createNativeWorkspaceProvider({ session, authorize: () => authorized ? allow() : denied,
      operations: { [operation]: async () => { calls++; entered.resolve(); await finish.promise; return available({ private: "never released" }); } } });
    const pending = operation === "readResource" ? provider.readResource(session, "resource") : provider[operation](session);
    await entered.promise; authorized = false; finish.resolve();
    assert.equal(await pending, denied); assert.equal(calls, 1);
  });
}

test("Native reads capture independent immutable data before their final asynchronous check", async () => {
  let checks = 0;
  const checking = deferred(), finish = deferred();
  const result = available({ items: [{ id: "original", blocks: [{ text: "authorized original" }] }], nextCursor: "native-original", snapshotRef: "snapshot" });
  const provider = createNativeWorkspaceProvider({ session, authorize: async () => {
    if (++checks === 2) { checking.resolve(); await finish.promise; } return allow();
  }, operations: { read: async () => result } });
  const pending = provider.read(session); await checking.promise;
  result.value.items[0].blocks[0].text = "later host-owned mutation"; result.value.nextCursor = "foreign-later";
  finish.resolve(); const released = await pending;
  assert.equal(released.value.items[0].blocks[0].text, "authorized original");
  assert.equal(released.value.nextCursor, "native-original");
  assert.equal(Object.isFrozen(released.value.items[0].blocks[0]), true);
  assert.equal(Object.isFrozen(result), false);
});

test("workspace listing rechecks actual scope authorization after asynchronous data retrieval", async () => {
  let authorized = true;
  const entered = deferred(), finish = deferred();
  const provider = createNativeWorkspaceProvider({ scopeRef: "scope", authorizeScope: () => authorized ? allow() : denied,
    operations: { listSessions: async () => { entered.resolve(); await finish.promise; return available({ items: [{ session }], nextCursor: null }); } } });
  const pending = provider.listSessions("scope"); await entered.promise;
  authorized = false; finish.resolve(); assert.equal(await pending, denied);
});

test("watch releases a captured original frame when the delegate mutates it during awaited authorization", async () => {
  let checks = 0, closed = false;
  const checking = deferred(), finish = deferred();
  const event = { id: "original", cursor: "native-original", session: { ...session }, kind: "host.row", payload: { text: "original" } };
  const provider = createNativeWorkspaceProvider({ session, authorize: async () => {
    if (++checks === 2) { checking.resolve(); await finish.promise; } return allow();
  }, operations: { watch: async function* () { try { yield event; } finally { closed = true; } } } });
  const iterator = provider.watch(session)[Symbol.asyncIterator](); const pending = iterator.next(); await checking.promise;
  event.session.generation = "replacement"; event.payload.text = "unqualified replacement"; event.cursor = "foreign-cursor";
  finish.resolve(); const released = (await pending).value;
  assert.equal(released.session.generation, session.generation); assert.equal(released.payload.text, "original");
  assert.equal(released.cursor, "native-original"); assert.equal(Object.isFrozen(released), true);
  await iterator.return(); assert.equal(closed, true);
});

test("watch does not yield a captured private frame when the final Host authorization is denied", async () => {
  let checks = 0, closed = false;
  const provider = createNativeWorkspaceProvider({ session, authorize: () => ++checks === 1 ? allow() : denied,
    operations: { watch: async function* () { try { yield { id: "private", cursor: "never-promote", session, kind: "host.row", payload: {} }; }
      finally { closed = true; } } } });
  const iterator = provider.watch(session)[Symbol.asyncIterator]();
  await assert.rejects(iterator.next(), error => error instanceof PortOperationUnavailable && error.code === "unauthorized");
  assert.equal(closed, true);
});

test("Native invalidation clears Native cursors and links while preserving the ACS replay position", () => {
  const state = { communicationCursor: "acs-original", nativeCursor: "native-old", nativeSession: session,
    sourceLinks: [{ messageHandle: "message", operationId: "operation", bindingEpoch: 1, nativeSession: session }] };
  assert.deepEqual(invalidateNativeState(state), { communicationCursor: "acs-original", nativeCursor: null, nativeSession: null, sourceLinks: [] });
  assert.equal(state.nativeCursor, "native-old"); assert.equal(state.sourceLinks.length, 1);
});
