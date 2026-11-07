import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { clientModelSchemas } from "../client-runtime-schema.ts";
import { awareTimestamp, ClientContractError, parseClientJson, validateClientModel } from "../client-validation.ts";
import { sealJson } from "../communication-http.ts";

test("generated validation graph is the admitted Runtime schema and is deeply immutable", () => {
  const source = JSON.parse(readFileSync(new URL("../../runtime/client_models.schema.json", import.meta.url), "utf8"));
  assert.deepEqual(clientModelSchemas, source.$defs);
  assert.ok(Object.isFrozen(clientModelSchemas));
  assert.ok(Object.isFrozen(clientModelSchemas.SendRequest.properties));
  assert.throws(() => { clientModelSchemas.SendRequest.additionalProperties = true; }, TypeError);
});

test("conditional branches, minimum properties, uniqueness and source evidence remain enforced", () => {
  assert.throws(() => validateClientModel("PreferencesWrite", {}), ClientContractError);
  assert.throws(() => validateClientModel("Draft", { content: "", attachment_refs: [], revision: 0, updated_at: "2026-11-06T00:00:00Z" }), ClientContractError);
  assert.throws(() => validateClientModel("SendRequest", { to: "peer", content: "x", reply_to: ["same", "same"] }), ClientContractError);
  assert.throws(() => validateClientModel("Capability", { name: "native_input", support: "supported", availability: "available", evidence_ref: null, valid_until: null, conditions: [] }), ClientContractError);
  assert.deepEqual(validateClientModel("Draft", { content: "未发送 🧭", attachment_refs: [], revision: 0, updated_at: null }),
    { content: "未发送 🧭", attachment_refs: [], revision: 0, updated_at: null });
});

test("aware calendar timestamps match Runtime strict dates instead of Date.parse normalization", () => {
  for (const value of ["2026-11-06T00:01:02Z", "2024-02-29t23:59:59.123z", "2026-11-06T00:01:02+09:00"]) assert.ok(awareTimestamp(value));
  for (const value of ["2026-02-30T00:00:00Z", "2025-02-29T00:00:00Z", "0000-01-01T00:00:00Z", "2026-11-06T00:00:00", "2026-11-06T00:00:60Z", "2026-11-06T00:00:00+24:00"]) assert.equal(awareTimestamp(value), false);
});

test("strict JSON rejects duplicate keys, non-finite/unsafe numbers, bad syntax and Unicode", () => {
  for (const text of ['{"a":1,"a":2}', '[1,]', '{"x":NaN}', '1e999', '9007199254740993', '01', 'true false', '"\\ud800"', '\ufeff{}', '{"x":1,}']) {
    assert.throws(() => parseClientJson(text), ClientContractError, text);
  }
  const safe = parseClientJson('{"__proto__":{"polluted":true},"ok":[true,null,-1.25]}');
  assert.equal(Object.getPrototypeOf(safe), Object.prototype);
  assert.equal(Object.hasOwn(safe, "__proto__"), true);
  assert.equal({}.polluted, undefined);
  assert.deepEqual(safe.ok, [true, null, -1.25]);
});

test("JSON depth, cycles and non-JSON prototypes fail before DTO acceptance", () => {
  assert.throws(() => parseClientJson("[".repeat(66) + "0" + "]".repeat(66)), ClientContractError);
  const cyclic = {}; cyclic.child = cyclic;
  for (const value of [cyclic, new Date(), { content: "x", attachment_refs: [], revision: Number.MAX_SAFE_INTEGER + 1, updated_at: null }]) {
    assert.throws(() => validateClientModel("Draft", value), ClientContractError);
  }
});

test("sealed write JSON cannot invoke accessors or hidden toJSON to change the approved intent", () => {
  let invoked = 0;
  const source = { to: "peer", content: "original" };
  Object.defineProperty(source, "toJSON", { value: () => { invoked++; return { to: "attacker", content: "changed", sender: "injected" }; } });
  assert.throws(() => sealJson("SendRequest", source), ClientContractError);
  const getter = { to: "peer" };
  Object.defineProperty(getter, "content", { enumerable: true, get() { invoked++; return "getter"; } });
  assert.throws(() => sealJson("SendRequest", getter), ClientContractError);
  assert.equal(invoked, 0);
});
