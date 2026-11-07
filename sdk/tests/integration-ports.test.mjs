import assert from "node:assert/strict";
import test from "node:test";
import { createManagementProvider, createNativeViewProvider, createNativeWorkspaceProvider,
  PortOperationUnavailable } from "../integration-ports.ts";

const session = Object.freeze({ providerRef: "host-provider", sessionRef: "host-session", hostRef: "host-machine",
  generation: "generation-7", authority: "harness" });
const allow = () => ({ available: true, value: undefined });
const denied = Object.freeze({ available: false, code: "unauthorized", reason: "Actual host permission revoked" });
const allowed = value => ({ available: true, value });

function unavailable(result, operation, code = "host_extension_required") {
  assert.deepEqual(result, { available: false, code, reason: `${operation}: ${code}` });
  assert.equal("value" in result, false);
}
async function unavailableStream(iterable, code = "host_extension_required") {
  await assert.rejects(async () => {
    for await (const value of iterable) assert.fail(`Unavailable stream emitted ${JSON.stringify(value)}`);
  }, error => error instanceof PortOperationUnavailable && error.operation === "watch" &&
    error.code === code && error.availability.available === false);
}

test("unconfigured native operations explicitly require a host extension, including watch", async () => {
  const provider = createNativeWorkspaceProvider();
  const calls = {
    capabilities: () => provider.capabilities(session), read: () => provider.read(session),
    act: () => provider.act(session, { kind: "resume" }, "request-1"), reveal: () => provider.reveal(session),
    listSessions: () => provider.listSessions("workspace-1"), state: () => provider.state(session),
    readResource: () => provider.readResource(session, "host-resource"),
    prepareAttachment: () => provider.prepareAttachment(session, "acs-attachment"),
  };
  for (const [operation, call] of Object.entries(calls)) unavailable(await call(), operation);
  await unavailableStream(provider.watch(session));
  const view = createNativeViewProvider();
  assert.deepEqual(Object.keys(view).sort(), ["act", "capabilities", "read", "reveal", "watch"]);
  assert.equal(Object.isFrozen(provider), true);
});

test("a configured method does not establish capabilities or host authorization", async () => {
  let calls = 0;
  const operations = { act: async () => { calls++; return allowed({ nativeOperationRef: "host-op", outcome: "accepted" }); } };
  unavailable(await createNativeViewProvider({ session, operations }).act(session, { kind: "resume" }, "request"), "act");
  const provider = createNativeViewProvider({ session, authorize: allow, operations });
  unavailable(await provider.capabilities(session), "capabilities");
  unavailable(await provider.read(session), "read");
  assert.equal(calls, 0);
});

for (const [field, replacement] of Object.entries({ providerRef: "other-provider", sessionRef: "other-session",
  hostRef: "other-host", generation: "generation-8", authority: "orca" })) {
  test(`the exact ${field} binding is checked before authorization and delegation`, async () => {
    let calls = 0;
    const provider = createNativeViewProvider({ session, authorize: () => { calls++; return allow(); },
      operations: { act: async () => { calls++; return allowed({ nativeOperationRef: "host-op", outcome: "accepted" }); } } });
    unavailable(await provider.act({ ...session, [field]: replacement }, { kind: "resume" }, "request"), "act", "unauthorized");
    assert.equal(calls, 0);
  });
}

test("denial is preserved without invoking host operations or granting from ACS-looking extra fields", async () => {
  let calls = 0;
  const provider = createNativeWorkspaceProvider({ session, authorize: () => denied,
    operations: { read: async () => { calls++; return allowed({ items: [], nextCursor: null, snapshotRef: "must-not-exist" }); },
      watch: async function* () { calls++; } } });
  assert.equal(await provider.read({ ...session, acsBearer: "synthetic-not-authority", role: "root" }), denied);
  await unavailableStream(provider.watch(session), "unauthorized");
  assert.equal(calls, 0);
});

test("malformed authorizer success fails closed", async () => {
  let calls = 0;
  const provider = createNativeViewProvider({ session, authorize: () => true,
    operations: { reveal: async () => { calls++; return allowed({ opened: true }); } } });
  unavailable(await provider.reveal(session), "reveal", "unauthorized");
  assert.equal(calls, 0);
});

test("host capabilities and unverified row provenance are passed through without inventing ACS replies", async () => {
  const capabilityResult = allowed(["host.read", "host.stop"]);
  const row = { id: "native-row-1", revision: 2, source: "transcript", role: "assistant",
    blocks: [{ hostBlockKind: "markdown", text: "Host-native text" }], nativeOrder: "host-order-z", timestamp: null };
  const pageResult = allowed({ items: [row], nextCursor: "native-page-only", snapshotRef: "host-snapshot" });
  const calls = [];
  const provider = createNativeViewProvider({ session, authorize: (actual, operation) => {
    calls.push(["authorize", operation, actual]); return allow();
  }, operations: { capabilities: async actual => { calls.push(["capabilities", actual]); return capabilityResult; },
    read: async (actual, cursor) => { calls.push(["read", actual, cursor]); return pageResult; } } });
  assert.deepEqual(await provider.capabilities(session), capabilityResult);
  assert.deepEqual(await provider.read(session, "native-previous-page"), pageResult);
  assert.equal("linkage" in row, false);
  assert.equal("explicitReplyHandle" in row, false);
  assert.deepEqual(calls.map(call => call.slice(0, 2)), [["authorize", "capabilities"], ["capabilities", session], ["authorize", "capabilities"],
    ["authorize", "read"], ["read", session], ["authorize", "read"]]);
  assert.equal(calls.at(-2)[2], "native-previous-page");
});

test("injected host SourceLink evidence remains unchanged and separate from communication cursors", async () => {
  const linkage = { messageHandle: "message-original", operationId: "operation-original", bindingEpoch: 12,
    nativeSession: session, nativeInputRef: "input-original", nativeTurnRef: "turn-original" };
  const result = allowed({ items: [{ id: "linked-row", revision: 1, source: "hook", role: "user", blocks: [],
    timestamp: null, linkage }], nextCursor: "native-cursor-41", snapshotRef: "native-snapshot" });
  const provider = createNativeViewProvider({ session, authorize: allow, operations: { read: async () => result } });
  const composite = { communicationCursor: "acs-cursor-99", nativeCursor: "native-cursor-40", nativeSession: session, sourceLinks: [] };
  const page = await provider.read(session, composite.nativeCursor);
  assert.deepEqual(page, result);
  assert.deepEqual(page.value.items[0].linkage, linkage);
  assert.equal(composite.communicationCursor, "acs-cursor-99");
  assert.equal(composite.nativeCursor, "native-cursor-40");
  assert.deepEqual(composite.sourceLinks, []);
});

test("an action and session are captured before asynchronous host authorization", async () => {
  let release;
  const wait = new Promise(resolve => { release = resolve; });
  const binding = { ...session };
  const requested = { ...session };
  const action = { kind: "answer_question", questionRef: "question-1", expectedRevision: "rev-4", answer: { options: ["A"] } };
  const receipt = allowed({ nativeOperationRef: "real-host-op", outcome: "unknown", reason: "Host could not confirm" });
  const calls = [];
  const operations = { async act(actual, submitted, requestId) {
    assert.equal(this, operations);
    calls.push({ actual, submitted, requestId });
    return receipt;
  } };
  const provider = createNativeViewProvider({ session: binding, authorize: async (actual, operation, details) => {
    assert.equal(operation, "act");
    assert.deepEqual(actual, session);
    assert.equal(details.action.questionRef, "question-1");
    assert.equal(details.requestId, "request-original");
    await wait;
    assert.equal(details.action.answer.options[0], "A");
    return allow();
  }, operations });
  const pending = provider.act(requested, action, "request-original");
  binding.generation = "later-binding";
  requested.hostRef = "later-target";
  action.questionRef = "later-question";
  action.answer.options[0] = "B";
  operations.act = async () => assert.fail("Configuration mutation replaced captured delegate");
  release();
  assert.equal(await pending, receipt);
  assert.deepEqual(calls, [{ actual: session, submitted: { kind: "answer_question", questionRef: "question-1",
    expectedRevision: "rev-4", answer: { options: ["A"] } }, requestId: "request-original" }]);
  assert.equal(Object.isFrozen(calls[0].submitted.answer.options), true);
});

test("each call rechecks host authorization and action-specific denial returns no accepted receipt", async () => {
  let authorized = true;
  let calls = 0;
  const provider = createNativeViewProvider({ session, authorize: (_session, _operation, details) =>
    authorized && details.action.kind === "resume" ? allow() : denied,
  operations: { act: async () => { calls++; return allowed({ nativeOperationRef: "host-resume", outcome: "accepted" }); } } });
  assert.equal((await provider.act(session, { kind: "resume" }, "first")).value.outcome, "accepted");
  authorized = false;
  assert.equal(await provider.act(session, { kind: "resume" }, "second"), denied);
  authorized = true;
  assert.equal(await provider.act(session, { kind: "clear" }, "third"), denied);
  assert.equal(calls, 1);
});

test("watch forwards only the native cursor, original AbortSignal and exact host events", async () => {
  const abort = new AbortController();
  const event = { id: "host-event", cursor: "native-cursor-next", session, kind: "host.turn.completed",
    payload: { hostEvidence: "evidence-1" } };
  let closed = false;
  const provider = createNativeViewProvider({ session, authorize: (_actual, operation, details) => {
    assert.equal(operation, "watch"); assert.equal(details.signal, abort.signal); return allow();
  }, operations: { watch: async function* (actual, after, signal) {
    assert.deepEqual(actual, session);
    assert.equal(after, "native-after");
    assert.equal(signal, abort.signal);
    try { yield event; assert.fail("Consumer cancellation was not forwarded"); } finally { closed = true; }
  } } });
  for await (const received of provider.watch(session, "native-after", abort.signal)) {
    assert.deepEqual(received, event); assert.notEqual(received, event); break;
  }
  assert.equal(closed, true);
  assert.equal("explicitReplyHandle" in event.payload, false);
});

test("watch rejects an event for another generation before releasing it", async () => {
  const provider = createNativeViewProvider({ session, authorize: allow, operations: { watch: async function* () {
    yield { id: "wrong-session", cursor: "must-not-advance", session: { ...session, generation: "new-generation" },
      kind: "host.turn", payload: {} };
  } } });
  await unavailableStream(provider.watch(session), "unauthorized");
});

test("watch rechecks live host authorization before every event and closes on revocation", async () => {
  let authorized = true, closed = false;
  const provider = createNativeViewProvider({ session, authorize: () => authorized ? allow() : denied,
    operations: { watch: async function* () {
      try {
        yield { id: "first", cursor: "native-first", session, kind: "host.row", payload: {} };
        yield { id: "second", cursor: "native-must-not-release", session, kind: "host.row", payload: {} };
      } finally { closed = true; }
    } } });
  const iterator = provider.watch(session)[Symbol.asyncIterator]();
  assert.equal((await iterator.next()).value.id, "first");
  authorized = false;
  await assert.rejects(iterator.next(), error => error instanceof PortOperationUnavailable && error.code === "unauthorized");
  assert.equal(closed, true);
});

test("workspace listing has a separate exact scope and host authorization gate", async () => {
  let calls = 0;
  const listed = allowed({ items: [{ session, title: "Actual host title", updatedAt: null, capabilities: ["host.read"] }],
    nextCursor: "host-list-next" });
  const operations = { listSessions: async (scope, cursor) => {
    calls++; assert.equal(scope, "workspace-bound"); assert.equal(cursor, "host-list-after"); return listed;
  } };
  const sessionOnly = createNativeWorkspaceProvider({ session, authorize: allow, operations });
  unavailable(await sessionOnly.listSessions("workspace-bound"), "listSessions");
  const provider = createNativeWorkspaceProvider({ session, authorize: allow, operations, scopeRef: "workspace-bound",
    authorizeScope: (scope, operation) => { assert.equal(scope, "workspace-bound"); assert.equal(operation, "listSessions"); return allow(); } });
  unavailable(await provider.listSessions("other-workspace"), "listSessions", "unauthorized");
  assert.deepEqual(await provider.listSessions("workspace-bound", "host-list-after"), listed);
  assert.equal(calls, 1);
});

test("workspace state/resources/attachment/reveal delegates preserve host results and arguments", async () => {
  const state = allowed({ revision: "host-rev", status: "unknown", evidenceClass: "unknown", pendingQuestions: [],
    pendingApprovals: [], model: null, effort: null, usage: null });
  const resource = allowed({ payload: { hostSchema: [1, 2] }, nextCursor: "resource-next" });
  const attachment = allowed({ nativeAttachmentRef: "host-native-file" });
  const opened = { available: false, code: "unsupported", reason: "Host cannot open a terminal" };
  const calls = [];
  const provider = createNativeWorkspaceProvider({ session, authorize: (actual, operation) => {
    assert.deepEqual(actual, session); calls.push(operation); return allow();
  }, operations: { state: async () => state,
    readResource: async (_session, ref, cursor) => { assert.equal(ref, "host-resource"); assert.equal(cursor, "resource-after"); return resource; },
    prepareAttachment: async (_session, ref) => { assert.equal(ref, "acs-attachment-ready"); return attachment; },
    reveal: async (_session, target) => { assert.deepEqual(target, { kind: "terminal", ref: "host-terminal" }); return opened; } } });
  assert.deepEqual(await provider.state(session), state);
  assert.deepEqual(await provider.readResource(session, "host-resource", "resource-after"), resource);
  assert.equal(await provider.prepareAttachment(session, "acs-attachment-ready"), attachment);
  assert.equal(await provider.reveal(session, { kind: "terminal", ref: "host-terminal" }), opened);
  assert.deepEqual(calls, ["state", "state", "readResource", "readResource", "prepareAttachment", "reveal"]);
});

test("native provider failures propagate rather than becoming empty transcripts or successful receipts", async () => {
  const error = new Error("Actual host disconnected");
  const provider = createNativeViewProvider({ session, authorize: allow, operations: {
    read: async () => { throw error; }, watch: async function* () { throw error; },
  } });
  await assert.rejects(provider.read(session), actual => actual === error);
  await assert.rejects(async () => { for await (const _event of provider.watch(session)) assert.fail(); }, actual => actual === error);
});

test("all absent management tools signal typed unavailability, including prototype names", async () => {
  const provider = createManagementProvider();
  for (const tool of ["configure_root", "configure_team", "create_route", "update_route", "toString"]) {
    await assert.rejects(provider.call(tool, {}), error => error instanceof PortOperationUnavailable &&
      error.operation === tool && error.code === "host_extension_required" && !error.availability.available);
  }
});

test("management delegates only configured tools with exact arguments and existing authorization failures", async () => {
  const args = { expected_revision: 3, metadata: { display_name: "Chosen route" } };
  const receipt = { route_id: "existing-route", revision: 4 };
  const error = new Error("Actual filtered management tool denied actor");
  const operations = { update_route: async function (received) {
    assert.equal(this, operations); assert.equal(received, args); return receipt;
  }, configure_root: async () => { throw error; } };
  const provider = createManagementProvider(operations);
  operations.update_route = async () => assert.fail("Delegate changed after construction");
  assert.equal(await provider.call("update_route", args), receipt);
  await assert.rejects(provider.call("configure_root", args), actual => actual === error);
  await assert.rejects(provider.call("create_route", args), PortOperationUnavailable);
});

test("invalid session registry bindings are refused during construction", () => {
  for (const field of ["providerRef", "sessionRef", "hostRef", "generation", "authority"]) {
    assert.throws(() => createNativeViewProvider({ session: { ...session, [field]: "" } }), TypeError);
  }
  assert.throws(() => createNativeViewProvider({ session: { ...session, authority: "acs-bearer" } }), TypeError);
});
