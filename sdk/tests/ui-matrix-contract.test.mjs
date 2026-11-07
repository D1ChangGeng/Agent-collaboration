// E1 controlled Host protocol only; this does not implement or qualify Orca.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createNativeWorkspaceProvider, PortOperationUnavailable } from "../integration-ports.ts";

const scope = JSON.parse(readFileSync(new URL("../../RFC_TEMP_SOURCE/ACS-Core-Stage-Agnostic-Revision-Pack-v1.1.0/contracts/ui-scope.json", import.meta.url)));
const session = { providerRef: "controlled-host", sessionRef: "native-session", hostRef: "host", generation: "generation-1", authority: "orca" };
const available = value => ({ available: true, value });
const denial = { available: false, code: "unauthorized", reason: "controlled host denied" };
const action = kind => ({ kind, ...({
  submit_prompt: { text: "controlled", attachmentRefs: [] }, stop_turn: { turnRef: "turn-1" },
  answer_question: { questionRef: "question-1", expectedRevision: "nonce-1", answer: { selected: "A" } },
  answer_approval: { approvalRef: "approval-1", expectedRevision: "nonce-1", decision: "approve" },
  update_queued_input: { inputRef: "input-1", expectedRevision: "queue-revision-1", text: "changed" },
  cancel_queued_input: { inputRef: "input-1", expectedRevision: "queue-revision-1" },
  stop_native_task: { nativeTaskRef: "task-1", expectedRevision: "revision-1" },
  stop_native_subagent: { childSessionRef: "child-1", expectedRevision: "revision-1" },
  set_model: { modelRef: "host-model", effort: "high" },
}[kind] ?? {}) });
const methods = {
  UI18: ["read", "watch"], UI19: ["read", "readResource", "watch"],
  UI20: ["read", "reveal:diff", "watch"],
  UI21: ["read", "act:stop_native_task", "act:stop_native_subagent", "watch"],
  UI22: ["read", "act:answer_question", "act:answer_approval", "watch"],
  UI23: ["capabilities", ...["submit_prompt", "stop_turn", "resume", "update_queued_input", "cancel_queued_input"].map(value => "act:"+value), "watch"],
  UI24: ["state", "read", "act:set_model", "watch"],
  UI25: ["listSessions", "read", "act:clear", "act:compact", "watch"],
  UI26: ["capabilities", "reveal:file", "reveal:terminal", "reveal:workspace", "reveal:diff"],
};
const invoke = (provider, method) => {
  const [name, kind] = method.split(":");
  if (name === "act") return provider.act(session, action(kind), "request:"+kind);
  if (name === "reveal") return provider.reveal(session, { kind, ref: "host-resource:"+kind });
  if (name === "listSessions") return provider.listSessions("bound-scope", "native-after");
  if (name === "readResource") return provider.readResource(session, "host-resource", "native-resource-after");
  if (name === "watch") return (async () => { const values=[]; for await(const value of provider.watch(session, "native-after")) values.push(value); return values; })();
  return provider[name](session, "native-after");
};

for (const row of scope.features.filter(value => value.authority === "host" && value.tier === "P1_required")) {
  test(row.id+" required Host methods stay unavailable without an installed delegate", async () => {
    assert.ok(methods[row.id], row.id);
    const provider = createNativeWorkspaceProvider();
    for (const method of methods[row.id]) {
      if(method === "watch") await assert.rejects(invoke(provider,method), error => error instanceof PortOperationUnavailable && error.code === "host_extension_required");
      else { const value=await invoke(provider,method); assert.equal(value.available,false); assert.equal(value.code,"host_extension_required"); assert.equal("value" in value,false); }
    }
  });
  test(row.id+" Host methods carry exact native scope and stop before callbacks on denial", async () => {
    let allowed=true; const delegated=[], authorized=[];
    const operations = {
      capabilities: async actual => { assert.deepEqual(actual,session); delegated.push("capabilities"); return available(["controlled-host-capability"]); },
      read: async actual => { assert.deepEqual(actual,session); delegated.push("read"); return available({ items: [
        { id:"native-source-1", revision:1, source:"transcript", role:"assistant", blocks:[{ tool:"tool-1", diff:"host-diff", childSessionRef:"child-1" }], timestamp:null }
      ], nextCursor:"native-only-after", snapshotRef:"host-snapshot" }); },
      readResource: async (actual,ref,cursor) => { assert.deepEqual(actual,session); assert.equal(ref,"host-resource"); assert.equal(cursor,"native-resource-after"); delegated.push("readResource"); return available({payload:{source:"host-long-output"},nextCursor:null}); },
      state: async actual => { assert.deepEqual(actual,session); delegated.push("state"); return available({revision:"host-revision",status:"unknown",evidenceClass:"unknown",pendingQuestions:[],pendingApprovals:[],model:"host-model",effort:"high",usage:{tokens:1}}); },
      listSessions: async (actual,cursor) => { assert.equal(actual,"bound-scope"); assert.equal(cursor,"native-after"); delegated.push("listSessions"); return available({items:[{session,title:"Host Session",updatedAt:null,capabilities:[]}],nextCursor:null}); },
      reveal: async (actual,resource) => { assert.deepEqual(actual,session); assert.equal(resource.ref,"host-resource:"+resource.kind); delegated.push("reveal:"+resource.kind); return available({opened:true}); },
      act: async (actual,submitted,requestId) => { assert.deepEqual(actual,session); assert.deepEqual(submitted,action(submitted.kind)); assert.equal(requestId,"request:"+submitted.kind); delegated.push("act:"+submitted.kind); return available({nativeOperationRef:"host-operation:"+requestId,outcome:"accepted"}); },
      watch: async function* (actual,cursor) { assert.deepEqual(actual,session); assert.equal(cursor,"native-after"); delegated.push("watch"); yield {id:"host-event",cursor:"native-next",session,kind:"native.changed",payload:{}}; },
    };
    const provider=createNativeWorkspaceProvider({session,scopeRef:"bound-scope",operations,
      authorize: (_actual,operation,details) => { authorized.push(details); return allowed?available(undefined):denial; },
      authorizeScope: () => allowed?available(undefined):denial});
    for(const method of methods[row.id]) { const result=await invoke(provider,method); if(method!=="watch") assert.equal(result.available,true); }
    assert.deepEqual(delegated,methods[row.id]);
    for(const method of methods[row.id].filter(value=>value.startsWith("act:"))) assert.ok(authorized.some(value=>value.operation==="act" && value.action.kind===method.slice(4)));
    allowed=false; const count=delegated.length;
    for(const method of methods[row.id]) {
      if(method==="watch") await assert.rejects(invoke(provider,method),error=>error instanceof PortOperationUnavailable && error.code==="unauthorized");
      else assert.deepEqual(await invoke(provider,method),denial);
    }
    assert.equal(delegated.length,count);
  });
}
