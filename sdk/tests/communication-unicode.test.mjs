import assert from "node:assert/strict";
import test from "node:test";
import { AcsSseParser, CommunicationEventStream } from "../communication-stream.ts";
import { createCommunicationState, projectionKey, reduceCommunication, validateCommunicationEvent } from "../communication-state.ts";

const maximum = "🧭".repeat(512), beyond = "🧭".repeat(513);
const fixture = { schema_version: "acs-event/1", event_id: maximum, cursor: "opaque-cursor", project_id: maximum,
  kind: "attachment.ready", resource_ref: maximum, resource_revision: 1, committed_at: "2026-11-06T00:00:00Z", auth_revision: "auth", payload: {} };

test("Stream Project IDs use the admitted 512-character limit including supplementary Unicode", () => {
  assert.doesNotThrow(() => new CommunicationEventStream({ projectId: maximum, url: "https://acs.invalid/events", getBearer: () => "valid" }));
  assert.throws(() => new CommunicationEventStream({ projectId: beyond, url: "https://acs.invalid/events", getBearer: () => "valid" }), TypeError);
});

test("metadata Event and state resource references preserve maximum-length supplementary characters", () => {
  assert.equal(validateCommunicationEvent(fixture).resource_ref, maximum);
  assert.equal(JSON.parse(projectionKey("attachment", maximum))[1], maximum);
  assert.throws(() => validateCommunicationEvent({ ...fixture, resource_ref: beyond }), TypeError);
  assert.throws(() => createCommunicationState(beyond), TypeError);
  const source = { snapshot_id: "snapshot", snapshot_expires_at: "2999-01-01T00:00:00Z", after_cursor: "cursor", auth_revision: "auth",
    actor: { address: maximum, principal_ref: maximum, level: "agent", agent_slot_id: maximum, auth_revision: "auth", allowed_actions: [] },
    contacts: [], conversations: [], receivers: [], notice_count: 0, pages: { contacts_cursor: null, conversations_cursor: null, receivers_cursor: null } };
  const loaded = reduceCommunication(createCommunicationState(maximum), { type: "snapshot", snapshot: source });
  assert.equal(loaded.actor.agent_slot_id, maximum);
  assert.equal(loaded.localWorkOwner.projectId, maximum);
});

test("Unicode character compatibility does not increase incremental SSE byte budgets", () => {
  const parser = new AcsSseParser({ maxBufferBytes: 4 });
  parser.push(new TextEncoder().encode("🧭"));
  assert.equal(parser.bufferedBytes, 4);
  assert.throws(() => parser.push(new TextEncoder().encode("a")), error => error.code === "buffer_overflow");
});
