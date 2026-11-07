// Actual ACS HTTP + controlled Native Host port. This does not qualify an Orca Host.
import assert from "node:assert/strict";
import { HttpCommunicationClient } from "../communication-client.ts";
import { createNativeWorkspaceProvider, invalidateNativeState } from "../integration-ports.ts";

const [endpoint, project, handle] = process.argv.slice(2);
const sdk = new HttpCommunicationClient({ endpoint, getBearer: () => process.env.ACS_NATIVE_SOURCE_TEST_TOKEN });
const allow = () => ({ available: true, value: undefined });
const available = value => ({ available: true, value });
const refused = reason => ({ available: false, code: "unauthorized", reason });
try {
  const before = await sdk.readMessage(project, handle, { includeNativeSource: true });
  assert.equal(before.native_source.available, true);
  const link = before.native_source.value, session = link.nativeSession;
  const text = before.message.content.text;
  const host = { generation: session.generation, model: "controlled-original", effort: "medium",
    approval: { ref: "pending-approval", revision: "turn-original:nonce-current", handled: false }, actions: 0,
    canReadSession: true, canReadChild: true, reads: 0, childAclChecks: 0 };
  const approval = { kind: "answer_approval", approvalRef: host.approval.ref,
    expectedRevision: host.approval.revision, decision: "approve" };
  const recorded = [];
  const provider = createNativeWorkspaceProvider({ session, authorize: actual =>
    actual.generation === host.generation && host.canReadSession ? allow() : refused("Controlled Host read/generation changed"),
    operations: {
      read: async () => {
        host.reads++; host.childAclChecks++;
        const items = [
        { id: "original-native-row", revision: 1, source: "transcript", role: "user", blocks: [{ text }], timestamp: null, linkage: link },
        { id: "independent-user-row", revision: 1, source: "transcript", role: "user", blocks: [{ text }], timestamp: null },
        { id: "tool-result", revision: 1, source: "transcript", role: "tool", blocks: [{ tool: "controlled", diff: "controlled" }], timestamp: null }
        ];
        // Child visibility is checked by the configured Host, independently
        // from permission to read the parent Session through the delegate.
        if (host.canReadChild) items.push({ id: "native-child-source-1", revision: 1, source: "transcript", role: "assistant",
          blocks: [{ type: "subagent", childSessionRef: "controlled-native-child-session", sourceId: "child-event-1",
            text: "CHILD_PRIVATE_SOURCE_BLOCK" }], timestamp: null });
        return available({ items, nextCursor: "native-only-cursor", snapshotRef: "controlled-host-snapshot" });
      },
      act: async (actual, action, requestId) => {
        // The configured Host owns this atomic current-state check. The SDK
        // does not treat its earlier permission check as an approval grant.
        if (actual.generation !== host.generation) return refused("Stale controlled generation");
        if (action.kind === "answer_approval" && (host.approval.handled || action.approvalRef !== host.approval.ref ||
            action.expectedRevision !== host.approval.revision)) return refused("Stale controlled approval nonce/turn");
        if (action.kind === "set_model") { host.model = action.modelRef; host.effort = action.effort; }
        if (action.kind === "compact" || action.kind === "clear") host.generation += ":" + action.kind;
        host.actions++; recorded.push({ action: action.kind, requestId });
        return available({ nativeOperationRef: "controlled-host:" + requestId, outcome: "accepted" });
      }
    } });
  const page = await provider.read(session, "native-before");
  assert.equal(page.available, true);
  assert.equal(page.value.items.length, 4);
  assert.deepEqual(page.value.items[0].linkage, link);
  assert.equal(page.value.items[1].blocks[0].text, text);
  assert.equal(page.value.items[1].linkage, undefined);
  assert.equal(page.value.items[2].role, "tool");
  const child = page.value.items[3];
  assert.equal(child.blocks[0].type, "subagent"); assert.equal(child.linkage, undefined);
  assert.notEqual(child.id, before.message.message_handle);
  assert.notEqual(child.blocks[0].childSessionRef, session.sessionRef);
  assert.equal(page.value.nextCursor, "native-only-cursor");
  host.canReadChild = false;
  const filtered = await provider.read(session, "native-before");
  assert.equal(filtered.available, true); assert.equal(filtered.value.items.length, 3);
  assert.ok(!JSON.stringify(filtered).includes("CHILD_PRIVATE_SOURCE_BLOCK"));
  assert.ok(!JSON.stringify(filtered).includes("controlled-native-child-session"));
  const readsBeforeDenial = host.reads;
  host.canReadSession = false;
  assert.equal((await provider.read(session)).available, false);
  assert.equal(host.reads, readsBeforeDenial);
  host.canReadSession = true;
  host.approval.handled = true;
  assert.equal((await provider.act(session, approval, "handled-approval")).available, false);
  host.approval.handled = false; host.approval.revision = "different-turn:nonce-new";
  assert.equal((await provider.act(session, approval, "replaced-turn")).available, false);
  assert.equal(host.actions, 0);
  assert.equal((await provider.act(session, { kind: "set_model", modelRef: "controlled-next", effort: "high" }, "model-setting")).available, true);
  assert.equal(host.model, "controlled-next"); assert.equal(host.effort, "high");
  assert.equal((await provider.act(session, { kind: "compact" }, "compact-setting")).available, true);
  assert.equal((await provider.read(session)).available, false);
  const local = { communicationCursor: "acs-unchanged", nativeCursor: page.value.nextCursor, nativeSession: session, sourceLinks: [link] };
  assert.deepEqual(invalidateNativeState(local), { communicationCursor: "acs-unchanged", nativeCursor: null, nativeSession: null, sourceLinks: [] });
  const nextSession = { ...session, generation: host.generation };
  const afterCompact = createNativeWorkspaceProvider({ session: nextSession,
    authorize: actual => actual.generation === host.generation ? allow() : refused("Stale generation"),
    operations: { act: async (actual, action, requestId) => {
      if (actual.generation !== host.generation || action.kind !== "clear") return refused("Stale/unsupported controlled action");
      host.generation += ":clear"; recorded.push({ action: action.kind, requestId });
      return available({ nativeOperationRef: "controlled-host:" + requestId, outcome: "accepted" });
    } } });
  assert.equal((await afterCompact.act(nextSession, { kind: "clear" }, "clear-setting")).available, true);
  assert.notEqual(nextSession.generation, host.generation);
  const after = await sdk.readMessage(project, handle, { includeNativeSource: true });
  assert.deepEqual(after.message, before.message);
  assert.deepEqual(after.native_source, before.native_source);
  assert.deepEqual(recorded.map(row => row.action), ["set_model", "compact", "clear"]);
  console.log(JSON.stringify({ evidence_class: "E2_actual_ACS_controlled_Host_port", same_text_unlinked: true,
    stale_nonce_denied: true, replaced_turn_denied: true, independent_native_cursor: true,
    settings_did_not_change_sender: true, clear_compact_preserved_acs_history: true,
    child_acl_enforced: true, child_source_unlinked: true,
    native_generation_from_controlled_host: host.generation, physical_host_qualified: false, model_request: false }));
} finally { sdk.close(); }
