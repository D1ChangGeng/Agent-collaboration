import assert from "node:assert/strict";
import { createHash, generateKeyPairSync, sign, verify } from "node:crypto";
import test from "node:test";
import { createOrcaReceiverPort, ORCA_CORE_SEALED_FORMAT } from "../orca-receiver-port.ts";

// Controlled verifier/Host protocol fixtures. They establish neither an installed
// Python ReceiverService integration nor an actual Orca Host/model qualification.
const canonical = value => value === null || typeof value !== "object" ? JSON.stringify(value) : Array.isArray(value) ?
  "[" + value.map(canonical).join(",") + "]" : "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
const sha = value => createHash("sha256").update(value).digest("hex");
const session = generation => ({ providerRef: "orca-provider", sessionRef: "native-session-1", hostRef: "host-1", generation, authority: "orca" });
const receiver = "receiver-1", address = "collaborator:project:slot-1";
function fixture({ timeout = 2000, activation = "invoke", deadline = null } = {}) {
  const keys = generateKeyPairSync("ed25519"), body = { prepare_request_id: "prepared-1", marker_receipt_id: "original-domain-marker" };
  const admission = { schema_version: ORCA_CORE_SEALED_FORMAT, purpose: "delivery.dispatch", authority_key_id: "key-1", authority_key_revision: 1,
    tenant_id: "tenant", authority_id: "authority", authority_incarnation: "incarnation", request_id: "dispatch-request-1", nonce: "e".repeat(64),
    method: "POST", path: "/v1/dispatch", body_sha256: sha(canonical(body)), message_id: "message-1", command_id: "command-1", operation_id: "core-operation-1",
    attempt_id: "attempt-1", dispatch_id: "dispatch-1", endpoint_id: receiver, endpoint_revision: 3, runtime_id: "runtime-1", runtime_revision: 1,
    node_id: "node-1", machine_id: "host-1", boot_incarnation: "boot-1", scope_id: "scope-1", agent_slot_id: "slot-1", accepted_revision: null,
    accepted_state_digest: "a".repeat(64), envelope_digest: "b".repeat(64), selection_digest: "c".repeat(64), invocation_digest: "d".repeat(64),
    journal_generation: 1, issued_at: "2026-11-06T00:00:00Z", deadline };
  const request = { admission, body, signature: sign(null, Buffer.from(canonical(admission)), keys.privateKey).toString("hex") };
  const bytes = Buffer.from(JSON.stringify(request));
  const command = { schema_version: "acs-adapter/1", operation_id: "delivery-invocation:attempt-1", receiver_id: receiver,
    message_handles: ["message:project:message-1"], canonical_hash: admission.envelope_digest, binding_epoch: 3, provider_generation: "generation-1",
    auth_revision: "core-prepared-auth", input_mode: "structured", sealed_envelope: { format: ORCA_CORE_SEALED_FORMAT, encoding: "base64", data: bytes.toString("base64") }, deadline };
  const original = { command, session: session("generation-1"), hostPrincipalRef: "host-user-1", address, authorityId: "authority",
    authorityIncarnation: "incarnation", scopeRef: "scope-1", activation, sealedBytesSha256: sha(bytes), verificationRef: "existing-prepared-receipt-1" };
  const counts = { authorize: 0, verify: 0, resolve: 0, admission: 0, reconcile: 0, enqueue: 0, observations: 0 };
  const state = { allowed: true, authRevision: "host-auth-1", receipt: null,
    owner: { receiverRef: receiver, address, bindingEpoch: 3, session: session("generation-1"), hostPrincipalRef: "host-user-1",
      authorityId: "authority", authorityIncarnation: "incarnation", scopeRef: "scope-1", ownerToken: {}, inputOwner: "orca" } };
  const accepted = () => ({ schema_version: "acs-adapter/1", operation_id: command.operation_id, outcome: "accepted", effect_possible: true,
    evidence_ref: "actual-host-receipt-1", native_input_ref: "actual-native-input-1", binding_epoch: 3, provider_generation: "generation-1", reason_code: null });
  const backend = {
    format: ORCA_CORE_SEALED_FORMAT,
    async verifyDispatch(captured, raw, context) {
      counts.verify++; context.assertCurrent();
      const signed = JSON.parse(Buffer.from(raw).toString());
      assert.deepEqual(Object.keys(signed).sort(), ["admission", "body", "signature"]);
      if (!verify(null, Buffer.from(canonical(signed.admission)), keys.publicKey, Buffer.from(signed.signature, "hex")) ||
          sha(canonical(signed.body)) !== signed.admission.body_sha256 || signed.body.prepare_request_id !== "prepared-1" ||
          canonical(captured) !== canonical(command)) throw new Error("PRIVATE_SIGNATURE_FAILURE");
      return { ...original, command: structuredClone(captured), sealedBytesSha256: sha(raw) };
    },
    async resolveOriginal(selected, operation, context) {
      counts.resolve++; context.assertCurrent();
      assert.equal(selected, receiver); assert.equal(operation, command.operation_id);
      // Existing original signature/domain lookup; sender deadline is not read authorization.
      assert.ok(verify(null, Buffer.from(canonical(request.admission)), keys.publicKey, Buffer.from(request.signature, "hex")));
      return original;
    },
  };
  const authorize = async (owner, operation, source) => {
    counts.authorize++;
    if (!state.allowed) return { available: false, code: "unauthorized", reason: "denied" };
    const target = source?.session ?? owner.session;
    return { available: true, value: { principalRef: owner.hostPrincipalRef, receiverRef: receiver, authRevision: state.authRevision,
      targetSessionRef: target.sessionRef, targetGeneration: target.generation, targetBindingEpoch: source?.command.binding_epoch ?? owner.bindingEpoch,
      targetProviderRef: target.providerRef, targetHostRef: target.hostRef, targetAuthority: target.authority,
      assertActive() { if (!state.allowed || state.authRevision !== this.authRevision) throw new Error("PRIVATE_REVOKED_HOST_GRANT"); } } };
  };
  const observation = () => ({ receiver_id: receiver, address, binding_epoch: state.owner.bindingEpoch, revision: 1,
    native_session_ref: state.owner.session.sessionRef, capability_scope: { adapter_id: "orca-host", adapter_version: "1", harness_kind: "orca",
      harness_version: "53fbfded", execution_host_ref: "host-1", binary_digest: null, config_digest: null, connection_epoch: 1,
      provider_generation: state.owner.session.generation }, capabilities: [], observations: [], allowed_actions: ["inspect"] });
  const host = {
    async describe(_owner, context) { counts.observations++; context.assertCurrent(); return observation(); },
    async observe(_owner, context) { counts.observations++; context.assertCurrent(); return observation(); },
    async admitVerified(input) {
      counts.admission++; input.assertCurrent(); input.grant.assertActive();
      if (!state.receipt) { counts.enqueue++; state.receipt = accepted(); }
      return state.receipt;
    },
    async reconcileOriginal(input) { counts.reconcile++; input.assertCurrent(); input.grant.assertActive(); return state.receipt ?? {
      ...accepted(), outcome: "unknown", native_input_ref: null, evidence_ref: null, reason_code: "original_operation_unobservable" }; },
  };
  const options = { currentOwnership: selected => selected === receiver ? state.owner : null, authorizeHost: authorize,
    verifier: backend, host, maximumSealedBytes: 65536, operationTimeoutMs: timeout };
  return { command, bytes, original, counts, state, backend, host, options, accepted, observation, port: () => createOrcaReceiverPort(options) };
}

test("describe/observe use actual supplied read callbacks and never perform admission", async () => {
  const f = fixture(), port = f.port();
  assert.deepEqual(await port.describe(receiver), { available: true, value: f.observation() });
  assert.deepEqual(await port.observe(receiver), { available: true, value: f.observation() });
  assert.equal(f.counts.observations, 2); assert.equal(f.counts.admission, 0); assert.equal(f.counts.enqueue, 0);
});

for (const missing of ["verifier", "atomic_host", "observation"]) test("missing " + missing + " is typed host_extension_required with zero Native effects", async () => {
  const f = fixture();
  if (missing === "verifier") delete f.options.verifier;
  else if (missing === "atomic_host") f.options.host = { describe: f.host.describe };
  else f.options.host = { admitVerified: f.host.admitVerified };
  const result = missing === "observation" ? await f.port().describe(receiver) : await f.port().admit(f.command);
  assert.equal(result.available, false); assert.equal(result.code, "host_extension_required");
  assert.equal(f.counts.verify, 0); assert.equal(f.counts.admission, 0); assert.equal(f.counts.enqueue, 0);
});

test("Core signature/body verification precedes the atomic Host entry, with exact original fields", async () => {
  const f = fixture(), port = f.port();
  assert.deepEqual(await port.admit(f.command), { available: true, value: f.accepted() });
  assert.equal(f.counts.verify, 1); assert.equal(f.counts.admission, 1); assert.equal(f.counts.enqueue, 1);
  // Explicit same-command retry is deduplicated by the existing Host fixture's
  // original receipt, not an SDK ledger or an automatic SDK resend.
  assert.deepEqual(await port.admit(f.command), { available: true, value: f.accepted() });
  assert.equal(f.counts.admission, 2); assert.equal(f.counts.enqueue, 1);
});

test("forged sealed bytes cannot be authorized by body flags or reach the Host", async () => {
  const f = fixture(), payload = JSON.parse(f.bytes.toString()); payload.body.marker_receipt_id = "forged";
  const forged = { ...f.command, sealed_envelope: { ...f.command.sealed_envelope, data: Buffer.from(JSON.stringify(payload)).toString("base64") } };
  const result = await f.port().admit(forged);
  assert.equal(result.available, false); assert.equal(result.code, "unauthorized");
  assert.equal(f.counts.admission, 0); assert.equal(f.counts.enqueue, 0);
  await assert.rejects(f.port().admit({ ...f.command, verified: true }));
});

for (const field of ["operation_id", "receiver_id", "message_handles", "canonical_hash", "binding_epoch", "provider_generation", "auth_revision"]) {
  test("verified original cannot substitute outer " + field, async () => {
    const f = fixture();
    f.options.verifier = { ...f.backend, async verifyDispatch() {
      const changed = structuredClone(f.original); changed.command[field] = field === "binding_epoch" ? 4 : field === "message_handles" ? ["message:project:other"] : "different";
      return changed;
    } };
    const result = await f.port().admit(f.command);
    assert.equal(result.available, false); assert.equal(f.counts.enqueue, 0); assert.equal(f.counts.admission, 0);
  });
}

test("message_only never reaches Host admission even with valid signing and independent Host authorization", async () => {
  const f = fixture({ activation: "message_only" });
  assert.equal((await f.port().admit(f.command)).code, "unsupported"); assert.equal(f.counts.enqueue, 0);
});

test("mutable command and verifier byte arguments cannot change the captured sealed intent", async () => {
  const f = fixture(); let release, entered;
  const gate = new Promise(resolve => { entered = resolve; }), pause = new Promise(resolve => { release = resolve; });
  const originalAuth = f.options.authorizeHost;
  f.options.authorizeHost = async (owner, operation, source, context) => {
    entered(); await pause;
    return originalAuth(owner, operation, source, context);
  };
  f.options.verifier = { ...f.backend, async verifyDispatch(...args) {
    const result = await f.backend.verifyDispatch(...args);
    args[1].fill(0); return result;
  } };
  const port = f.port(), caller = structuredClone(f.command), pending = port.admit(caller);
  await gate; caller.operation_id = "changed"; caller.message_handles[0] = "changed"; caller.sealed_envelope.data = "AAAA"; release();
  assert.equal((await pending).value.operation_id, f.command.operation_id); assert.equal(f.counts.enqueue, 1);
});

for (const race of ["owner", "principal", "grant", "same_value_registration"]) test(race + " change after Core verification blocks before Host mutation", async () => {
  const f = fixture();
  f.options.verifier = { ...f.backend, async verifyDispatch(...args) {
    const result = await f.backend.verifyDispatch(...args);
    if (race === "owner") f.state.owner = { ...f.state.owner, session: session("generation-2") };
    else if (race === "principal") f.state.owner = { ...f.state.owner, hostPrincipalRef: "other-host-user" };
    else if (race === "grant") f.state.allowed = false;
    else f.state.owner = { ...f.state.owner, ownerToken: {} };
    return result;
  } };
  assert.equal((await f.port().admit(f.command)).available, false);
  assert.equal(f.counts.enqueue, 0); assert.equal(f.counts.admission, 0);
});

test("an external Driver ownership claim during verification fences the Orca bridge before Host entry", async () => {
  const f = fixture();
  let entered, release;
  const atVerification = new Promise(resolve => { entered = resolve; });
  const pendingVerification = new Promise(resolve => { release = resolve; });
  f.options.verifier = { ...f.backend, async verifyDispatch(...args) {
    const verified = await f.backend.verifyDispatch(...args);
    entered(); await pendingVerification; return verified;
  } };
  const port = f.port(), attempt = port.admit(f.command);
  await atVerification;
  // Explicit controlled registry claim by a different input owner. There is no
  // actual external Driver or installed Host in this protocol-level fixture.
  f.state.owner = { ...f.state.owner, inputOwner: "external_driver", ownerToken: {} };
  release();
  assert.equal((await attempt).available, false);
  assert.equal(f.counts.admission, 0); assert.equal(f.counts.enqueue, 0);
  const verified = f.counts.verify;
  assert.equal((await port.admit(f.command)).code, "unauthorized");
  assert.equal(f.counts.verify, verified);
  assert.equal(f.counts.admission, 0); assert.equal(f.counts.enqueue, 0);
});

test("missing Host implementation cannot be supplied by database injection callbacks or body authority flags", async () => {
  const f = fixture();
  let privateCalls = 0;
  delete f.options.host; delete f.options.verifier;
  f.options.sqlitePath = "controlled-unopened-private-Orca-database";
  f.options.injectNativeDatabase = () => { privateCalls++; throw new Error("must not be called"); };
  await assert.rejects(f.port().admit({ ...f.command, root: true, owner: "orca" }),
    error => error.code === "invalid_contract");
  const result = await f.port().admit(f.command);
  assert.equal(result.available, false); assert.equal(result.code, "host_extension_required");
  assert.equal(privateCalls, 0); assert.equal(f.counts.enqueue, 0); assert.equal(f.counts.admission, 0);
});

test("live Host grant is checked again inside prepared-input admission before synchronous enqueue", async () => {
  const f = fixture();
  f.options.host = { ...f.host, async admitVerified(input) {
    f.counts.admission++; input.assertCurrent();
    await Promise.resolve(); f.state.allowed = false;
    input.assertCurrent(); f.counts.enqueue++; return f.accepted();
  } };
  const result = await f.port().admit(f.command);
  assert.equal(result.value.outcome, "unknown"); assert.equal(result.value.effect_possible, true);
  assert.equal(result.value.operation_id, f.command.operation_id); assert.equal(f.counts.admission, 1); assert.equal(f.counts.enqueue, 0);
});

for (const fault of ["throw_after_enqueue", "auth_loss_after_enqueue", "raw_pending", "wrong_result_operation"]) test(fault + " preserves original unknown and never resubmits", async () => {
  const f = fixture();
  f.options.host = { ...f.host, async admitVerified(input) {
    f.counts.admission++; input.assertCurrent(); f.counts.enqueue++; f.state.receipt = f.accepted();
    if (fault === "throw_after_enqueue") throw new Error("PRIVATE_HOST_FAILURE");
    if (fault === "auth_loss_after_enqueue") f.state.allowed = false;
    if (fault === "raw_pending") return { ok: true, pending: true };
    if (fault === "wrong_result_operation") return { ...f.accepted(), operation_id: "another-operation" };
    return f.accepted();
  } };
  const result = await f.port().admit(f.command);
  assert.equal(result.value.outcome, "unknown"); assert.equal(result.value.operation_id, f.command.operation_id);
  assert.equal(result.value.effect_possible, true); assert.equal(result.value.evidence_ref, null); assert.equal(result.value.native_input_ref, null);
  assert.equal(f.counts.admission, 1); assert.equal(f.counts.enqueue, 1); assert.ok(!JSON.stringify(result).includes("PRIVATE"));
});

test("original reconciliation reads historical ACK after deadline/rebind without admitting into the new generation", async () => {
  const f = fixture({ deadline: "2001-01-01T00:00:00Z" }); f.state.receipt = f.accepted();
  f.state.owner = { ...f.state.owner, bindingEpoch: 4, session: session("generation-2"), ownerToken: {} };
  const result = await f.port().reconcile(receiver, f.command.operation_id);
  assert.equal(result.value.outcome, "accepted"); assert.equal(result.value.binding_epoch, 3); assert.equal(result.value.provider_generation, "generation-1");
  assert.equal(f.counts.resolve, 1); assert.equal(f.counts.reconcile, 1); assert.equal(f.counts.admission, 0); assert.equal(f.counts.enqueue, 0);
});

test("reconcile exact original operation and generation are validated rather than resubmitted", async () => {
  const f = fixture();
  f.options.verifier = { ...f.backend, async resolveOriginal() { return { ...f.original, command: { ...f.command, operation_id: "unrelated" } }; } };
  const result = await f.port().reconcile(receiver, f.command.operation_id);
  assert.equal(result.available, false); assert.equal(result.code, "unauthorized");
  assert.ok(!JSON.stringify(result).includes("unrelated")); assert.equal(f.counts.reconcile, 0); assert.equal(f.counts.enqueue, 0);
});

for (const field of ["scopeRef", "address", "authorityId", "authorityIncarnation", "hostPrincipalRef"]) test("reconcile wrong original " + field + " is unavailable before Host read, not a foreign unknown receipt", async () => {
  const f = fixture(), foreign = "FOREIGN_PRIVATE_IDENTITY_" + field;
  f.options.verifier = { ...f.backend, async resolveOriginal() { return { ...f.original, [field]: foreign }; } };
  const result = await f.port().reconcile(receiver, f.command.operation_id);
  assert.equal(result.available, false); assert.equal(result.code, "unauthorized"); assert.ok(!JSON.stringify(result).includes("FOREIGN_PRIVATE"));
  assert.equal(f.counts.reconcile, 0); assert.equal(f.counts.admission, 0); assert.equal(f.counts.enqueue, 0);
});

test("original Host READ denial before reconcile entry has no available possible-effect receipt", async () => {
  const f = fixture(), authorize = f.options.authorizeHost;
  f.options.authorizeHost = async (owner, mode, source, context) => source ? { available: false, code: "unauthorized", reason: "denied" } : authorize(owner, mode, source, context);
  const result = await f.port().reconcile(receiver, f.command.operation_id);
  assert.equal(result.available, false); assert.equal(result.code, "unauthorized"); assert.equal(Object.hasOwn(result, "value"), false);
  assert.equal(f.counts.resolve, 1); assert.equal(f.counts.reconcile, 0); assert.equal(f.counts.admission, 0); assert.equal(f.counts.enqueue, 0);
});

test("original readback loss after authorized reconcile entry stays unknown for the requested operation only", async () => {
  const f = fixture();
  f.options.host = { ...f.host, async reconcileOriginal() { f.counts.reconcile++; throw new Error("PRIVATE_READBACK_LOSS"); } };
  const result = await f.port().reconcile(receiver, f.command.operation_id);
  assert.equal(result.value.outcome, "unknown"); assert.equal(result.value.operation_id, f.command.operation_id);
  assert.equal(result.value.effect_possible, true); assert.equal(f.counts.reconcile, 1); assert.equal(f.counts.admission, 0);
});

test("unavailable verifier is bounded; close during a possible Host effect stays unknown and terminal", async () => {
  const f = fixture({ timeout: 5 }); f.options.verifier = { ...f.backend, verifyDispatch: () => new Promise(() => {}) };
  assert.equal((await f.port().admit(f.command)).available, false); assert.equal(f.counts.enqueue, 0);
  const g = fixture(); let started;
  const entered = new Promise(resolve => { started = resolve; });
  g.options.host = { ...g.host, async admitVerified() { g.counts.admission++; started(); return new Promise(() => {}); } };
  const port = g.port(), pending = port.admit(g.command); await entered; port.close();
  assert.equal((await pending).value.outcome, "unknown"); assert.equal((await port.describe(receiver)).available, false);
  assert.equal(g.counts.admission, 1);
});

test("wrong observation identity and JSON-only authorization success cannot expose data or admit", async () => {
  const f = fixture(); f.options.host = { ...f.host, async describe() { return { ...f.observation(), native_session_ref: "other-session" }; } };
  assert.equal((await f.port().describe(receiver)).available, false);
  const g = fixture(); g.options.authorizeHost = async owner => ({ available: true, value: { principalRef: owner.hostPrincipalRef,
    receiverRef: receiver, authRevision: "auth", targetSessionRef: owner.session.sessionRef, targetGeneration: owner.session.generation, targetBindingEpoch: owner.bindingEpoch } });
  assert.equal((await g.port().admit(g.command)).available, false); assert.equal(g.counts.enqueue, 0);
});

for (const field of ["targetProviderRef", "targetHostRef", "targetAuthority"]) test("Host authorization must bind the exact " + field + " namespace", async () => {
  const f = fixture(), authorize = f.options.authorizeHost;
  f.options.authorizeHost = async (...args) => {
    const grant = await authorize(...args);
    return { available: true, value: { ...grant.value, [field]: field === "targetAuthority" ? "harness" : "another-namespace" } };
  };
  const result = await f.port().admit(f.command);
  assert.equal(result.available, false); assert.equal(result.code, "unauthorized"); assert.equal(f.counts.verify, 0); assert.equal(f.counts.admission, 0); assert.equal(f.counts.enqueue, 0);
});
