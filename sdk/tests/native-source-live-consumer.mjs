// Actual SDK/TCP consumer. Expected refs come from the test's real Core/Driver records.
import assert from "node:assert/strict";
import { HttpCommunicationClient } from "../communication-client.ts";

const [endpoint, project, handle, operation, protocol] = process.argv.slice(2);
const token = process.env.ACS_NATIVE_SOURCE_TEST_TOKEN;
const client = new HttpCommunicationClient({ endpoint, getBearer: () => token });
try {
  const basic = await client.readMessage(project, handle);
  assert.equal(basic.native_source, undefined);
  const response = await client.readMessage(project, handle, { includeNativeSource: true });
  assert.equal(response.native_source.available, true);
  const source = response.native_source.value;
  assert.equal(source.messageHandle, handle);
  assert.equal(source.operationId, operation);
  assert.equal(source.nativeSession.providerRef, "trusted-original-provider");
  assert.equal(source.nativeSession.authority, "harness");
  assert.equal(Boolean(source.nativeTurnRef), protocol === "codex");
  assert.equal(Boolean(source.nativeInputRef), protocol === "opencode");
  assert.equal(typeof response.native_source.evidence_ref, "string");
  console.log(JSON.stringify({ available: true, operation_id: source.operationId,
    native_session: source.nativeSession.sessionRef, native_turn: source.nativeTurnRef ?? null,
    native_input: source.nativeInputRef ?? null, sdk: "production", tcp: true }));
} finally { client.close(); }
