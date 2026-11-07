import assert from "node:assert/strict";
import test from "node:test";
import {
  AcsSseParser, CommunicationEventStream, CursorMismatchError, SnapshotRequiredError,
  StreamAuthenticationError, StreamReplayError,
} from "../communication-stream.ts";

const encoder = new TextEncoder();
const project = "synthetic-project";
function event(index, overrides = {}) {
  return { schema_version: "acs-event/1", event_id: "synthetic-event-" + index, cursor: "opaque-position-" + index,
    project_id: project, kind: "message.committed", resource_ref: "message:synthetic-project:original", resource_revision: index,
    committed_at: "2026-11-06T00:00:00Z", auth_revision: "synthetic-auth", payload: {}, ...overrides };
}
function frame(value, { id = value.cursor, kind = value.kind } = {}) {
  return encoder.encode("id: " + id + "\nevent: " + kind + "\ndata: " + JSON.stringify(value) + "\n\n");
}
function concatenate(chunks) {
  const result = new Uint8Array(chunks.reduce((size, chunk) => size + chunk.length, 0));
  let offset = 0;
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length; }
  return result;
}
function response(chunks, error = false) {
  let index = 0;
  return new Response(new ReadableStream({
    pull(controller) {
      if (index < chunks.length) controller.enqueue(chunks[index++]);
      else if (error) controller.error(new Error("private transport detail must not be echoed"));
      else controller.close();
    },
  }), { headers: { "Content-Type": "text/event-stream; charset=utf-8" } });
}
function stream(fetch, options = {}) {
  return new CommunicationEventStream({ projectId: project, url: "https://acs.example.test/api/communication/v1/projects/synthetic-project/events",
    getBearer: () => "synthetic-bearer", fetch, ...options });
}

test("SSE parses UTF-8 byte boundaries, BOM, multiline data and split CRLF exactly", () => {
  const parser = new AcsSseParser();
  const source = encoder.encode('\ufeff: heartbeat\r\nid: opaque-one\r\nevent: message.committed\r\ndata: {"text":"🙂",\r\ndata: "number":2}\r\n\r\n: trailing heartbeat');
  for (const byte of source) parser.push(Uint8Array.of(byte));
  const first = parser.next();
  assert.equal(first.id, "opaque-one");
  assert.equal(first.event, "message.committed");
  assert.deepEqual(JSON.parse(first.data), { text: "🙂", number: 2 });
  assert.equal(first.data, '{"text":"🙂",\n"number":2}');
  assert.equal(parser.resumeCursor, "opaque-one");
  assert.equal(parser.next(), null);
  parser.finish();
});

test("comments and id-only heartbeats never emit a domain event or advance the emitted cursor", () => {
  const parser = new AcsSseParser();
  for (let index = 0; index < 1000; index++) parser.push(encoder.encode(": ping\n\n"));
  parser.push(encoder.encode("id: not-a-delivered-domain-position\n\n"));
  assert.equal(parser.next(), null);
  assert.equal(parser.resumeCursor, null);
  parser.finish();
});

test("mixed line endings and deterministic arbitrary byte fragmentation preserve every complete frame", () => {
  const values = Array.from({ length: 10 }, (_, index) => event(index + 1, { payload: { reason_code: "Unicode🙂行" } }));
  const text = "\ufeff: heartbeat\r\n\r\n" + values.map((value, index) => {
    const newline = ["\r\n", "\r", "\n"][index % 3];
    return "id: " + value.cursor + newline + "data: " + JSON.stringify(value) + newline + newline;
  }).join("");
  const bytes = encoder.encode(text);
  for (let seed = 1; seed <= 30; seed++) {
    const parser = new AcsSseParser();
    const parsed = [];
    let offset = 0, current = seed;
    while (offset < bytes.length) {
      current = (current * 48271) % 2147483647;
      const end = Math.min(bytes.length, offset + current % 31 + 1);
      parser.push(bytes.subarray(offset, end));
      let next;
      while ((next = parser.next()) !== null) parsed.push(JSON.parse(next.data));
      assert.ok(parser.bufferedBytes >= 0 && parser.bufferedBytes <= 1048576);
      offset = end;
    }
    parser.finish();
    assert.deepEqual(parsed, values);
    assert.equal(parser.resumeCursor, values.at(-1).cursor);
  }
});

test("an incomplete event or UTF-8 sequence fails closed from the last delivered parser cursor", () => {
  for (const suffix of [encoder.encode("data: {\"partial\":"), Uint8Array.of(0xf0, 0x9f)]) {
    const parser = new AcsSseParser();
    parser.push(encoder.encode("id: prior\ndata: complete\n\n"));
    parser.next();
    parser.push(suffix);
    assert.throws(() => parser.finish(), error => error instanceof StreamReplayError && error.resumeCursor === "prior");
    assert.equal(parser.resumeCursor, "prior");
  }
});

test("SSE bounds queued events at 256 and bytes at one MiB without skipping unconsumed positions", () => {
  const parser = new AcsSseParser();
  parser.push(encoder.encode("id: prior\ndata: delivered\n\n"));
  parser.next();
  const queued = encoder.encode(Array.from({ length: 257 }, (_, index) => "id: queued-" + index + "\ndata: item\n\n").join(""));
  assert.throws(() => parser.push(queued), error => error instanceof StreamReplayError && error.code === "slow_consumer" && error.resumeCursor === "prior");
  assert.equal(parser.bufferedEvents, 0);
  assert.equal(parser.resumeCursor, "prior");
  const partial = new AcsSseParser();
  partial.push(encoder.encode(Array.from({ length: 256 }, (_, index) => "id: item-" + index + "\ndata: complete\n\n").join("")));
  assert.throws(() => partial.push(encoder.encode("data: beginning-event-257\n")), error => error.code === "slow_consumer");
  const bytes = new AcsSseParser();
  assert.throws(() => bytes.push(new Uint8Array(1048577)), error => error.code === "buffer_overflow" && error.resumeCursor === null);
  assert.throws(() => new AcsSseParser({ maxEvents: 257 }), TypeError);
  assert.throws(() => new AcsSseParser({ maxBufferBytes: 1048577 }), TypeError);
});

test("caller bearer and matching opaque Last-Event-ID/after_cursor form one explicit GET connection", async () => {
  let calls = 0, credentials = 0;
  const client = stream(async (url, options) => {
    calls++;
    assert.equal(options.method, "GET");
    assert.equal(options.credentials, "omit");
    assert.equal(options.redirect, "error");
    assert.equal(url.searchParams.get("after_cursor"), "prior-position");
    assert.equal(options.headers.get("Last-Event-ID"), "prior-position");
    assert.equal(options.headers.get("Authorization"), "Bearer provided-at-call-time");
    assert.equal(url.searchParams.has("token"), false);
    return response([encoder.encode(": ping\n\n"), frame(event(1))]);
  }, { afterCursor: "prior-position", lastEventId: "prior-position", getBearer: () => { credentials++; return "provided-at-call-time"; } });
  const events = [];
  for await (const value of client.events()) events.push(value);
  assert.equal(events.length, 1);
  assert.equal(client.resumeCursor, event(1).cursor);
  assert.equal(calls, 1);
  assert.equal(credentials, 1);
});

test("conflicting caller cursors and URL credentials are rejected before token lookup or fetch", () => {
  let calls = 0;
  const fetch = () => { calls++; throw new Error("must not connect"); };
  assert.throws(() => stream(fetch, { afterCursor: "one", lastEventId: "two" }), CursorMismatchError);
  assert.throws(() => stream(fetch, { url: "https://acs.example.test/events?after_cursor=other", afterCursor: "one" }), CursorMismatchError);
  for (const url of ["https://user:secret@acs.example.test/events", "https://acs.example.test/events?access_token=secret"]) {
    assert.throws(() => stream(fetch, { url }), TypeError);
  }
  assert.equal(calls, 0);
});

test("HTTP 410 requires a new snapshot and 401/403 clear the reconnect cursor", async () => {
  for (const status of [410, 401, 403]) {
    let requests = 0;
    const client = stream(async () => { requests++; return new Response("private body ignored", { status }); }, { afterCursor: "old-position" });
    const iterator = client.events();
    await assert.rejects(iterator.next(), error => {
      assert.equal(error.requiresSnapshot, true);
      assert.equal(error.status, status);
      assert.equal(error.resumeCursor, null);
      assert.ok(status === 410 ? error instanceof SnapshotRequiredError : error instanceof StreamAuthenticationError);
      assert.equal(error.message.includes("private"), false);
      return true;
    });
    assert.equal(requests, 1);
    assert.equal(client.resumeCursor, null);
    assert.equal(client.requiresSnapshot, true);
    await assert.rejects(client.events().next(), SnapshotRequiredError);
    assert.equal(requests, 1);
  }
});

test("a network interruption replays from the last emitted position and never reconnects automatically", async () => {
  let requests = 0;
  const client = stream(async (url, options) => {
    requests++;
    if (requests === 1) return response([frame(event(1))], true);
    assert.equal(url.searchParams.get("after_cursor"), event(1).cursor);
    assert.equal(options.headers.get("Last-Event-ID"), event(1).cursor);
    return response([frame(event(2))]);
  });
  const received = [];
  await assert.rejects(async () => { for await (const value of client.events()) received.push(value); }, error =>
    error instanceof StreamReplayError && error.code === "network_error" && error.resumeCursor === event(1).cursor && !error.message.includes("private"));
  assert.deepEqual(received.map(item => item.event_id), [event(1).event_id]);
  assert.equal(requests, 1);
  assert.equal(client.resumeCursor, event(1).cursor);
  for await (const value of client.events()) received.push(value);
  assert.equal(requests, 2);
  assert.equal(client.resumeCursor, event(2).cursor);
});

test("slow-consumer overflow never promotes the newest queued server cursor", async () => {
  const pending = concatenate(Array.from({ length: 257 }, (_, index) => frame(event(index + 2))));
  const client = stream(async () => response([frame(event(1)), pending]));
  const received = [];
  await assert.rejects(async () => { for await (const value of client.events()) received.push(value); }, error =>
    error instanceof StreamReplayError && error.code === "slow_consumer" && error.resumeCursor === event(1).cursor);
  assert.deepEqual(received.map(item => item.event_id), [event(1).event_id]);
  assert.equal(client.resumeCursor, event(1).cursor);
});

test("invalid envelope, foreign project and SSE-id mismatch never advance the client checkpoint", async () => {
  for (const invalid of [frame(event(2), { id: "unrelated-sse-position" }), frame(event(2, { project_id: "foreign-project" })),
    frame(event(2, { payload: { driver_journal: "not-an-event-metadata-field" } }))]) {
    const client = stream(async () => response([frame(event(1)), invalid]));
    const received = [];
    await assert.rejects(async () => { for await (const value of client.events()) received.push(value); }, StreamReplayError);
    assert.equal(received.length, 1);
    assert.equal(client.resumeCursor, event(1).cursor);
  }
});

test("permission/resync controls reach the reducer once then close with a snapshot requirement", async () => {
  for (const kind of ["permission.changed", "resync.required"]) {
    let calls = 0;
    const control = event(0, { kind, resource_ref: null, cursor: "control-does-not-authorize-skipping", payload: { reset_required: true } });
    const client = stream(async () => { calls++; return response([frame(control), frame(event(9))]); });
    const iterator = client.events();
    assert.equal((await iterator.next()).value.kind, kind);
    assert.equal(client.resumeCursor, null);
    await assert.rejects(iterator.next(), SnapshotRequiredError);
    assert.equal(calls, 1);
  }
});

test("authorization revision changes require resnapshot rather than accepting a new private context", async () => {
  const client = stream(async () => response([frame(event(1, { auth_revision: "different-current-authorization" }))]),
    { authRevision: "synthetic-auth", afterCursor: "prior-position" });
  await assert.rejects(client.events().next(), error => error instanceof SnapshotRequiredError && error.reason === "authorization_changed");
  assert.equal(client.resumeCursor, null);
});

test("a permission control carrying private identifiers is not delivered to the consumer", async () => {
  const control = event(0, { kind: "permission.changed", resource_ref: "message:synthetic-project:private",
    payload: { reset_required: true, message_handle: "message:synthetic-project:private" } });
  const client = stream(async () => response([frame(control)]));
  await assert.rejects(client.events().next(), error => error instanceof SnapshotRequiredError && error.reason === "unsafe_control_envelope");
  assert.equal(client.resumeCursor, null);
});

test("explicit abort cancels a stalled read and keeps the last emitted checkpoint", { timeout: 2000 }, async () => {
  let cancelled = 0, requests = 0;
  const body = new ReadableStream({ start(controller) { controller.enqueue(frame(event(1))); }, cancel() { cancelled++; } });
  const client = stream(async () => { requests++; return new Response(body, { headers: { "Content-Type": "text/event-stream" } }); });
  const abort = new AbortController();
  const iterator = client.events({ signal: abort.signal });
  assert.equal((await iterator.next()).value.event_id, event(1).event_id);
  const pending = iterator.next();
  abort.abort();
  await assert.rejects(pending, error => error instanceof StreamReplayError && error.code === "aborted" && error.resumeCursor === event(1).cursor);
  assert.equal(cancelled, 1);
  assert.equal(requests, 1);
});

test("consumer return closes the read-only transport without another request", async () => {
  let cancelled = 0, requests = 0;
  const body = new ReadableStream({ start(controller) { controller.enqueue(frame(event(1))); }, cancel() { cancelled++; } });
  const client = stream(async () => { requests++; return new Response(body, { headers: { "Content-Type": "text/event-stream" } }); });
  for await (const value of client.events()) { assert.equal(value.event_id, event(1).event_id); break; }
  assert.equal(cancelled, 1);
  assert.equal(requests, 1);
  assert.equal(client.resumeCursor, event(1).cursor);
});
