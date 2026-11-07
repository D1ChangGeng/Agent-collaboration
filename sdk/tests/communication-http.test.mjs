import assert from "node:assert/strict";
import test from "node:test";
import { ClientContractError } from "../client-validation.ts";
import { checkedBearer, checkedEndpoint, CommunicationHttpError, CommunicationHttpTransport, ifMatch, readBoundedBytes, reference, resourceUrl } from "../communication-http.ts";

const endpoint = "https://acs.invalid/api/communication/v1/";
const json = (value, init = {}) => new Response(JSON.stringify(value), { headers: { "content-type": "application/json" }, ...init });
const problem = effect => ({ error: { code: "authorization_denied", message: "PRIVATE_ERROR_TEXT", retryable: false, effect_state: effect, details: {} }, request_id: "opaque-request" });

test("endpoint/bearer admission and encoded references preserve the owned endpoint", () => {
  for (const url of ["https://user:pass@acs.invalid/", "file:///private", "https://acs.invalid/#x", "https://acs.invalid/?token=private"]) assert.throws(() => checkedEndpoint(url));
  for (const token of ["", "unsafe\r\nheader", "x".repeat(8193)]) assert.throws(() => checkedBearer(token));
  const url = resourceUrl(new URL(endpoint), ["projects", "项目", "messages", "message:p:id/a"]);
  assert.equal(url.origin, "https://acs.invalid");
  assert.ok(url.pathname.endsWith("message%3Ap%3Aid%2Fa"));
  for (const dot of [".", ".."]) assert.throws(() => resourceUrl(new URL(endpoint), ["projects", dot, "messages"]), TypeError);
  const astral = "🧭".repeat(512);
  assert.equal(reference(astral), astral);
  assert.equal(decodeURIComponent(resourceUrl(new URL(endpoint), ["projects", astral]).pathname.split("/").at(-1)), astral);
  assert.throws(() => reference("🧭".repeat(513)), TypeError);
  assert.equal(ifMatch("9223372036854775806"), '"9223372036854775806"');
  for (const value of ["01", "-1", "*", '"1"', "9223372036854775807", Number.MAX_SAFE_INTEGER + 1]) assert.throws(() => ifMatch(value), TypeError);
});

test("one request uses current bearer, manual redirect policy and no ambient credentials", async () => {
  let calls = 0;
  const transport = new CommunicationHttpTransport({ endpoint, getBearer: () => "valid-token", fetch: async (url, options) => {
    calls++; assert.equal(url.origin, "https://acs.invalid"); assert.equal(options.headers.get("Authorization"), "Bearer valid-token");
    assert.equal(options.credentials, "omit"); assert.equal(options.redirect, "error"); return json({});
  } });
  const exposed = transport.endpoint; exposed.hostname = "other.invalid";
  assert.deepEqual(await transport.json("Empty", { segments: ["meta"] }), {});
  assert.equal(calls, 1);
});

test("attempted POST/PUT/DELETE network errors are unknown and never retried", async () => {
  for (const method of ["POST", "PUT", "DELETE"]) {
    let calls = 0;
    const transport = new CommunicationHttpTransport({ endpoint, getBearer: () => "valid-token", fetch: async () => { calls++; throw new Error("PRIVATE_NETWORK_DETAIL"); } });
    await assert.rejects(transport.json("Empty", { method, segments: ["messages"], key: "exact-key" }), error =>
      error instanceof CommunicationHttpError && error.code === "network_error" && error.effectState === "unknown" && !String(error).includes("PRIVATE"));
    assert.equal(calls, 1);
  }
});

test("validated Problem preserves known effects while malformed and bad 2xx DTO writes stay unknown", async () => {
  for (const response of [json(problem("none"), { status: 403 }), json(problem("committed"), { status: 409 })]) {
    const transport = new CommunicationHttpTransport({ endpoint, getBearer: () => "valid", fetch: async () => response });
    await assert.rejects(transport.json("Empty", { method: "POST", segments: ["messages"] }), error => {
      assert.equal(error.code, "authorization_denied"); assert.equal(error.requestId, "opaque-request");
      assert.ok(!error.message.includes("PRIVATE")); return ["none", "committed"].includes(error.effectState);
    });
  }
  for (const response of [new Response("PRIVATE_HTML_BODY", { status: 500 }), json({ forbidden: true }),
    new Response('{"x":1,"x":2}', { headers: { "content-type": "application/json" } })]) {
    const transport = new CommunicationHttpTransport({ endpoint, getBearer: () => "valid", fetch: async () => response });
    await assert.rejects(transport.json("Empty", { method: "PUT", segments: ["draft"] }), error =>
      error instanceof CommunicationHttpError && error.effectState === "unknown" && !String(error).includes("PRIVATE"));
  }
});

test("request bytes are sealed before awaiting bearer acquisition", async () => {
  let release, actual;
  const bearer = new Promise(resolve => { release = resolve; });
  const transport = new CommunicationHttpTransport({ endpoint, getBearer: () => bearer, fetch: async (_url, options) => { actual = options.body; return json({}); } });
  const bytes = new Uint8Array([1, 2, 3]);
  const result = transport.json("Empty", { method: "PUT", segments: ["content"], body: bytes });
  bytes.fill(9); release("valid"); await result;
  assert.deepEqual([...actual], [1, 2, 3]);
});

test("response reader enforces actual bytes, declared length, fatal UTF-8 and cancels oversized streams", async () => {
  let cancelled = 0;
  const stream = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array([1, 2, 3])); }, cancel() { cancelled++; } });
  await assert.rejects(readBoundedBytes(new Response(stream), 2), ClientContractError);
  assert.equal(cancelled, 1);
  await assert.rejects(readBoundedBytes(new Response("x", { headers: { "content-length": "5" } }), 8), ClientContractError);
  const transport = new CommunicationHttpTransport({ endpoint, getBearer: () => "valid", fetch: async () => new Response(new Uint8Array([255]), { headers: { "content-type": "application/json" } }) });
  await assert.rejects(transport.json("Empty", { method: "POST", segments: ["messages"] }), error => error.effectState === "unknown");
});

test("owner/context reset fences a late successful response and does not turn an attempted write into none", async () => {
  let release, started;
  const gate = new Promise(resolve => { started = resolve; });
  const transport = new CommunicationHttpTransport({ endpoint, getBearer: () => "valid", fetch: async () => { started(); return new Promise(resolve => { release = resolve; }); } });
  const result = transport.json("Empty", { method: "POST", segments: ["messages"] });
  await gate; transport.advanceContext(); release(json({}));
  await assert.rejects(result, error => error.code === "authorization_changed" && error.effectState === "unknown");
  transport.close();
  await assert.rejects(transport.json("Empty", { method: "POST", segments: ["messages"] }), error => error.effectState === "none");
});
