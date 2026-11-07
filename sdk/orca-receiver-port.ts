import type { NativeAdmissionCommand, NativeAdmissionResult, Receiver } from "./client-contracts.ts";
import type { Json, NativeSessionRef, OrcaReceiverPort, Result, Unavailable } from "./integration-ports.ts";
import { parseClientJson, validateClientModel } from "./client-validation.ts";
import { reference, sealJson } from "./communication-http.ts";

export const ORCA_CORE_SEALED_FORMAT = "acs-delivery-admission/1";
export type OrcaReceiverOperation = "describe" | "observe" | "admit" | "reconcile";
export type OrcaReceiverOwnership = Readonly<{
  receiverRef: string; address: string; bindingEpoch: number; session: Readonly<NativeSessionRef>;
  hostPrincipalRef: string; authorityId: string; authorityIncarnation: string; scopeRef: string;
  /** Actual trusted Host registration/current-child token, not a wire assertion. */
  ownerToken: object;
  inputOwner: "orca";
}>;
export type OrcaReceiverHostGrant = Readonly<{
  principalRef: string; receiverRef: string; authRevision: string;
  targetSessionRef: string; targetGeneration: string; targetBindingEpoch: number;
  targetProviderRef: string; targetHostRef: string; targetAuthority: NativeSessionRef["authority"];
  /** Live synchronous Host scope/credential check, e.g. PluginHostCallScope.assertActive. */
  assertActive: () => void;
}>;
/** Returned only by a configured adapter around the EXISTING signed receiver verifier/ledger.
 * verifyDispatch must run ReceiverService verification, current Core auth, signed
 * prepared-fact/boot/marker matching and SignedHarnessAdapter outer correlation.
 * resolveOriginal uses historical identity verification plus current read auth;
 * an expired sender deadline must not erase a positive original receipt.
 */
export type VerifiedOrcaCoreOperation = Readonly<{
  command: NativeAdmissionCommand; session: Readonly<NativeSessionRef>;
  hostPrincipalRef: string; address: string; authorityId: string; authorityIncarnation: string; scopeRef: string;
  activation: "invoke" | "message_only";
  sealedBytesSha256: string;
  /** Reference to the existing verified prepare/operation, never a new SDK ledger. */
  verificationRef: string;
}>;
export type OrcaReceiverCallContext = Readonly<{ signal: AbortSignal; assertCurrent: () => void }>;
export interface ExistingSignedReceiverVerifier {
  readonly format: typeof ORCA_CORE_SEALED_FORMAT;
  verifyDispatch(command: NativeAdmissionCommand, signedRequestBytes: Uint8Array,
    context: OrcaReceiverCallContext): Promise<VerifiedOrcaCoreOperation>;
  resolveOriginal(receiverRef: string, operationId: string,
    context: OrcaReceiverCallContext): Promise<VerifiedOrcaCoreOperation>;
}
export type OrcaVerifiedHostInput = Readonly<{
  operation: VerifiedOrcaCoreOperation; ownership: OrcaReceiverOwnership; grant: OrcaReceiverHostGrant;
  signal: AbortSignal; assertCurrent: () => void;
}>;
export interface OrcaAtomicReceiverHostExtension {
  /** Actual Host observations; never inferred from these method names. */
  describe?(ownership: OrcaReceiverOwnership, context: OrcaReceiverCallContext): Promise<Receiver>;
  observe?(ownership: OrcaReceiverOwnership, context: OrcaReceiverCallContext): Promise<Receiver>;
  /** Must assert exact current child inside Host serialize -> validate -> prepare ->
   * validate -> synchronous enqueue. Ordinary expectedRuntimeFence is insufficient.
   * Return actual settlement evidence, never journal ok/pending as Native ACK.
   */
  admitVerified?(input: OrcaVerifiedHostInput): Promise<NativeAdmissionResult>;
  /** Original dedup domain only. It must never call admit/send or create a Session. */
  reconcileOriginal?(input: OrcaVerifiedHostInput): Promise<NativeAdmissionResult>;
}
export type OrcaReceiverPortOptions = {
  currentOwnership: (receiverRef: string) => OrcaReceiverOwnership | null;
  authorizeHost: (ownership: OrcaReceiverOwnership, operation: OrcaReceiverOperation,
    original: VerifiedOrcaCoreOperation | null, context: OrcaReceiverCallContext) => Promise<Result<OrcaReceiverHostGrant>>;
  verifier?: ExistingSignedReceiverVerifier;
  host?: OrcaAtomicReceiverHostExtension;
  /** Negotiated bound of the existing enrolled receiver, not an inferred Host capability. */
  maximumSealedBytes: number;
  operationTimeoutMs?: number;
};
export class OrcaReceiverProtocolError extends Error {
  readonly code: string;
  constructor(code: string) { super("Orca receiver protocol boundary refused the operation"); this.name = "OrcaReceiverProtocolError"; this.code = code; }
}
const unavailable = (code: Unavailable["code"], reason: string): Unavailable => ({ available: false, code, reason });
function freeze(value: unknown): void {
  if (value !== null && typeof value === "object") { for (const child of Object.values(value)) freeze(child); Object.freeze(value); }
}
function json(value: unknown): Json {
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number" && Number.isFinite(value)) return value;
  if (Array.isArray(value)) return value.map(json);
  if (value !== null && typeof value === "object") {
    const result: Record<string, Json> = {};
    for (const [key, child] of Object.entries(value)) Object.defineProperty(result, key, { value: json(child), enumerable: true });
    return result;
  }
  throw new OrcaReceiverProtocolError("invalid_host_json");
}
function command(value: unknown): NativeAdmissionCommand {
  const captured = validateClientModel("NativeAdmissionCommand", parseClientJson(sealJson("NativeAdmissionCommand", value)));
  freeze(captured); return captured;
}
function nativeSession(value: Readonly<NativeSessionRef>): Readonly<NativeSessionRef> {
  for (const field of [value.providerRef, value.sessionRef, value.hostRef, value.generation]) reference(field);
  if (value.authority !== "orca" && value.authority !== "harness") throw new OrcaReceiverProtocolError("invalid_native_authority");
  return Object.freeze({ providerRef: value.providerRef, sessionRef: value.sessionRef, hostRef: value.hostRef,
    generation: value.generation, authority: value.authority });
}
function ownership(value: OrcaReceiverOwnership | null, receiver: string): OrcaReceiverOwnership {
  if (!value || value.receiverRef !== receiver || value.inputOwner !== "orca" || !value.ownerToken || typeof value.ownerToken !== "object" ||
      !Number.isSafeInteger(value.bindingEpoch) || value.bindingEpoch < 0) throw new OrcaReceiverProtocolError("receiver_not_owned");
  for (const item of [value.receiverRef, value.address, value.hostPrincipalRef, value.authorityId, value.authorityIncarnation, value.scopeRef]) reference(item);
  return Object.freeze({ receiverRef: value.receiverRef, address: value.address, bindingEpoch: value.bindingEpoch,
    session: nativeSession(value.session), hostPrincipalRef: value.hostPrincipalRef, authorityId: value.authorityId,
    authorityIncarnation: value.authorityIncarnation, scopeRef: value.scopeRef, ownerToken: value.ownerToken, inputOwner: "orca" });
}
function ownerIdentity(value: OrcaReceiverOwnership): string {
  return JSON.stringify([value.receiverRef, value.address, value.bindingEpoch, value.session, value.hostPrincipalRef,
    value.authorityId, value.authorityIncarnation, value.scopeRef, value.inputOwner]);
}
function sessionIdentity(value: Readonly<NativeSessionRef>): string {
  return JSON.stringify([value.providerRef, value.sessionRef, value.hostRef, value.generation, value.authority]);
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object") return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(Reflect.get(value, key))).join(",") + "}";
  return JSON.stringify(value);
}
function decode(value: NativeAdmissionCommand, maximum: number): Uint8Array {
  const text = value.sealed_envelope.data;
  if (value.sealed_envelope.format !== ORCA_CORE_SEALED_FORMAT || value.sealed_envelope.encoding !== "base64" ||
      text.length > Math.ceil(maximum / 3) * 4 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(text)) {
    throw new OrcaReceiverProtocolError("unnegotiated_or_invalid_sealed_format");
  }
  let raw: string;
  try { raw = atob(text); } catch { throw new OrcaReceiverProtocolError("invalid_sealed_encoding"); }
  if (!raw.length || raw.length > maximum) throw new OrcaReceiverProtocolError("sealed_request_size");
  return Uint8Array.from(raw, char => char.charCodeAt(0));
}
async function digest(bytes: Uint8Array): Promise<string> {
  const result = await globalThis.crypto.subtle.digest("SHA-256", new Uint8Array(bytes));
  return [...new Uint8Array(result)].map(value => value.toString(16).padStart(2, "0")).join("");
}
function original(value: VerifiedOrcaCoreOperation): VerifiedOrcaCoreOperation {
  const captured = command(value.command);
  for (const item of [value.hostPrincipalRef, value.address, value.authorityId, value.authorityIncarnation, value.scopeRef, value.verificationRef]) reference(item);
  if (!/^[a-f0-9]{64}$/.test(value.sealedBytesSha256) || !["invoke", "message_only"].includes(value.activation)) throw new OrcaReceiverProtocolError("invalid_core_verification");
  const result = { command: captured, session: nativeSession(value.session), hostPrincipalRef: value.hostPrincipalRef,
    address: value.address, authorityId: value.authorityId, authorityIncarnation: value.authorityIncarnation,
    scopeRef: value.scopeRef, activation: value.activation, sealedBytesSha256: value.sealedBytesSha256, verificationRef: value.verificationRef };
  freeze(result); return result;
}
function unknown(operation: VerifiedOrcaCoreOperation, reason: string): Result<NativeAdmissionResult> {
  return { available: true, value: validateClientModel("NativeAdmissionResult", { schema_version: "acs-adapter/1",
    operation_id: operation.command.operation_id, outcome: "unknown", effect_possible: true, evidence_ref: null,
    native_input_ref: null, binding_epoch: operation.command.binding_epoch, provider_generation: operation.command.provider_generation, reason_code: reason }) };
}

/** Specific sealed-receiver bridge. It owns no operation ledger, credentials or Driver. */
export class TrustedOrcaReceiverPort implements OrcaReceiverPort {
  private current: OrcaReceiverPortOptions["currentOwnership"];
  private authorize: OrcaReceiverPortOptions["authorizeHost"];
  private verify: ExistingSignedReceiverVerifier["verifyDispatch"] | undefined;
  private resolve: ExistingSignedReceiverVerifier["resolveOriginal"] | undefined;
  private describeHost: OrcaAtomicReceiverHostExtension["describe"];
  private observeHost: OrcaAtomicReceiverHostExtension["observe"];
  private admitHost: OrcaAtomicReceiverHostExtension["admitVerified"];
  private reconcileHost: OrcaAtomicReceiverHostExtension["reconcileOriginal"];
  private maximum: number;
  private timeout: number;
  private epoch = 0;
  private closed = false;
  private active = new Set<AbortController>();
  constructor(options: OrcaReceiverPortOptions) {
    if (typeof options.currentOwnership !== "function" || typeof options.authorizeHost !== "function" ||
        !Number.isSafeInteger(options.maximumSealedBytes) || options.maximumSealedBytes < 1 || options.maximumSealedBytes > 16 * 1024 * 1024) {
      throw new TypeError("A trusted current Host owner, independent Host authorizer and negotiated sealed-byte bound are required");
    }
    this.current = options.currentOwnership; this.authorize = options.authorizeHost; this.maximum = options.maximumSealedBytes;
    this.timeout = options.operationTimeoutMs ?? 10000;
    if (!Number.isSafeInteger(this.timeout) || this.timeout < 1 || this.timeout > 60000) throw new TypeError("Invalid Orca receiver operation budget");
    if (options.verifier?.format === ORCA_CORE_SEALED_FORMAT) {
      this.verify = options.verifier.verifyDispatch?.bind(options.verifier); this.resolve = options.verifier.resolveOriginal?.bind(options.verifier);
    }
    this.describeHost = options.host?.describe?.bind(options.host); this.observeHost = options.host?.observe?.bind(options.host);
    this.admitHost = options.host?.admitVerified?.bind(options.host); this.reconcileHost = options.host?.reconcileOriginal?.bind(options.host);
  }
  close(): void { this.closed = true; this.epoch++; for (const controller of this.active) controller.abort(); }
  private scope(receiver: string) {
    if (this.closed) throw new OrcaReceiverProtocolError("receiver_context_closed");
    const selected = reference(receiver), captured = ownership(this.current(selected), selected), epoch = this.epoch;
    const controller = new AbortController(); this.active.add(controller);
    const timer = setTimeout(() => controller.abort(), this.timeout);
    let liveGrant: (() => void) | undefined;
    const assertCurrent = () => {
      if (controller.signal.aborted || epoch !== this.epoch) throw new OrcaReceiverProtocolError("receiver_context_expired");
      const now = ownership(this.current(selected), selected);
      if (now.ownerToken !== captured.ownerToken || ownerIdentity(now) !== ownerIdentity(captured)) throw new OrcaReceiverProtocolError("receiver_owner_changed");
      liveGrant?.();
    };
    const context = Object.freeze({ signal: controller.signal, assertCurrent });
    let authRevision: string | undefined;
    const wait = async <T>(promise: Promise<T>): Promise<T> => {
      // A trusted callback may already have started before this synchronous
      // fence runs. Always observe its rejection, even if the fence refuses it.
      void promise.catch(() => {});
      assertCurrent();
      const aborted = new Promise<never>((_resolve, reject) => {
        const abort = () => reject(new OrcaReceiverProtocolError("receiver_context_expired"));
        if (controller.signal.aborted) abort(); else controller.signal.addEventListener("abort", abort, { once: true });
        promise.finally(() => controller.signal.removeEventListener("abort", abort)).catch(() => {});
      });
      const value = await Promise.race([promise, aborted]); assertCurrent(); return value;
    };
    const authorized = async (operation: OrcaReceiverOperation, source: VerifiedOrcaCoreOperation | null = null) => {
      const response = await wait(this.authorize(captured, operation, source, context));
      if (!response || response.available !== true) throw new OrcaReceiverProtocolError("host_authorization_denied");
      const grant = response.value, target = source?.session ?? captured.session, targetEpoch = source?.command.binding_epoch ?? captured.bindingEpoch;
      if (!grant || typeof grant.assertActive !== "function" || grant.principalRef !== captured.hostPrincipalRef || grant.receiverRef !== selected ||
          grant.targetSessionRef !== target.sessionRef || grant.targetGeneration !== target.generation || grant.targetBindingEpoch !== targetEpoch ||
          grant.targetProviderRef !== target.providerRef || grant.targetHostRef !== target.hostRef || grant.targetAuthority !== target.authority) {
        throw new OrcaReceiverProtocolError("host_authorization_denied");
      }
      reference(grant.authRevision);
      if (authRevision !== undefined && authRevision !== grant.authRevision) throw new OrcaReceiverProtocolError("host_authorization_changed");
      const active = grant.assertActive.bind(grant);
      const assertActive = () => {
        const result: unknown = active();
        if (result !== undefined) {
          if (result instanceof Promise) void result.catch(() => {});
          throw new OrcaReceiverProtocolError("host_live_authorization_check_invalid");
        }
      };
      assertActive(); liveGrant = assertActive;
      authRevision = grant.authRevision;
      return Object.freeze({ principalRef: grant.principalRef, receiverRef: grant.receiverRef, authRevision: grant.authRevision,
        targetSessionRef: grant.targetSessionRef, targetGeneration: grant.targetGeneration, targetBindingEpoch: grant.targetBindingEpoch,
        targetProviderRef: grant.targetProviderRef, targetHostRef: grant.targetHostRef, targetAuthority: grant.targetAuthority, assertActive });
    };
    const dispose = () => { clearTimeout(timer); controller.abort(); this.active.delete(controller); };
    return { captured, context, wait, authorized, dispose };
  }
  private async read(receiver: string, mode: "describe" | "observe"): Promise<Result<Json>> {
    let scope: ReturnType<TrustedOrcaReceiverPort["scope"]>;
    try { scope = this.scope(receiver); } catch { return unavailable("unauthorized", "receiver_not_owned"); }
    try {
      await scope.authorized(mode);
      const method = mode === "describe" ? this.describeHost : this.observeHost;
      if (!method) return unavailable("host_extension_required", "orca_receiver_observation_port_missing");
      const value = await scope.wait(method(scope.captured, scope.context));
      const result = validateClientModel("Receiver", parseClientJson(sealJson("Receiver", value)));
      if (result.receiver_id !== scope.captured.receiverRef || result.address !== scope.captured.address || result.binding_epoch !== scope.captured.bindingEpoch ||
          result.native_session_ref !== scope.captured.session.sessionRef || result.capability_scope.execution_host_ref !== scope.captured.session.hostRef ||
          result.capability_scope.provider_generation !== scope.captured.session.generation) throw new OrcaReceiverProtocolError("observation_scope_mismatch");
      await scope.authorized(mode); return { available: true, value: json(result) };
    } catch { return unavailable("unauthorized", "orca_receiver_observation_not_authorized"); }
    finally { scope.dispose(); }
  }
  describe(receiverRef: string): Promise<Result<Json>> { return this.read(receiverRef, "describe"); }
  observe(receiverRef: string): Promise<Result<Json>> { return this.read(receiverRef, "observe"); }
  async admit(value: NativeAdmissionCommand): Promise<Result<NativeAdmissionResult>> {
    const captured = command(value);
    let scope: ReturnType<TrustedOrcaReceiverPort["scope"]>;
    try { scope = this.scope(captured.receiver_id); } catch { return unavailable("unauthorized", "receiver_not_owned"); }
    let verified: VerifiedOrcaCoreOperation | undefined, entered = false;
    try {
      await scope.authorized("admit");
      if (!this.verify || !this.admitHost) return unavailable("host_extension_required", "signed_verifier_or_atomic_orca_admission_missing");
      const bytes = decode(captured, this.maximum), sealedHash = await scope.wait(digest(bytes));
      verified = original(await scope.wait(this.verify(captured, new Uint8Array(bytes), scope.context)));
      if (canonical(verified.command) !== canonical(captured) || verified.sealedBytesSha256 !== sealedHash ||
          verified.command.provider_generation !== verified.session.generation || verified.command.receiver_id !== scope.captured.receiverRef ||
          verified.command.binding_epoch !== scope.captured.bindingEpoch || sessionIdentity(verified.session) !== sessionIdentity(scope.captured.session) ||
          verified.hostPrincipalRef !== scope.captured.hostPrincipalRef || verified.address !== scope.captured.address || verified.scopeRef !== scope.captured.scopeRef ||
          verified.authorityId !== scope.captured.authorityId || verified.authorityIncarnation !== scope.captured.authorityIncarnation) {
        throw new OrcaReceiverProtocolError("verified_original_scope_mismatch");
      }
      if (verified.activation !== "invoke") return unavailable("unsupported", "message_only_has_no_native_admission");
      const grant = await scope.authorized("admit", verified);
      scope.context.assertCurrent(); entered = true;
      const response = await scope.wait(this.admitHost({ operation: verified, ownership: scope.captured, grant, ...scope.context }));
      const result = this.result(response, verified);
      await scope.authorized("admit", verified); return { available: true, value: result };
    } catch {
      return entered && verified ? unknown(verified, "orca_admission_observation_unknown") : unavailable("unauthorized", "orca_sealed_admission_not_authorized");
    } finally { scope.dispose(); }
  }
  async reconcile(receiverRef: string, operationId: string): Promise<Result<NativeAdmissionResult>> {
    const receiver = reference(receiverRef), operation = reference(operationId);
    let scope: ReturnType<TrustedOrcaReceiverPort["scope"]>;
    try { scope = this.scope(receiver); } catch { return unavailable("unauthorized", "receiver_not_owned"); }
    let verified: VerifiedOrcaCoreOperation | undefined, correlated: VerifiedOrcaCoreOperation | undefined, entered = false;
    try {
      await scope.authorized("reconcile");
      if (!this.resolve || !this.reconcileHost) return unavailable("host_extension_required", "original_orca_reconciliation_port_missing");
      verified = original(await scope.wait(this.resolve(receiver, operation, scope.context)));
      const sealedHash = await scope.wait(digest(decode(verified.command, this.maximum)));
      if (verified.command.receiver_id !== receiver || verified.command.operation_id !== operation || verified.hostPrincipalRef !== scope.captured.hostPrincipalRef ||
          verified.address !== scope.captured.address || verified.scopeRef !== scope.captured.scopeRef || verified.authorityId !== scope.captured.authorityId ||
          verified.authorityIncarnation !== scope.captured.authorityIncarnation || verified.command.provider_generation !== verified.session.generation || verified.sealedBytesSha256 !== sealedHash) {
        throw new OrcaReceiverProtocolError("original_reconcile_scope_mismatch");
      }
      correlated = verified;
      const grant = await scope.authorized("reconcile", correlated);
      scope.context.assertCurrent(); entered = true;
      const response = await scope.wait(this.reconcileHost({ operation: correlated, ownership: scope.captured, grant, ...scope.context }));
      const result = this.result(response, correlated);
      await scope.authorized("reconcile", correlated); return { available: true, value: result };
    } catch {
      return entered && correlated ? unknown(correlated, "original_orca_observation_unknown") : unavailable("unauthorized", "original_orca_reconciliation_not_authorized");
    } finally { scope.dispose(); }
  }
  private result(value: NativeAdmissionResult, verified: VerifiedOrcaCoreOperation): NativeAdmissionResult {
    const result = validateClientModel("NativeAdmissionResult", parseClientJson(sealJson("NativeAdmissionResult", value)));
    if (result.operation_id !== verified.command.operation_id || result.binding_epoch !== verified.command.binding_epoch ||
        result.provider_generation !== verified.command.provider_generation) throw new OrcaReceiverProtocolError("original_result_scope_mismatch");
    freeze(result); return result;
  }
}
export function createOrcaReceiverPort(options: OrcaReceiverPortOptions): TrustedOrcaReceiverPort { return new TrustedOrcaReceiverPort(options); }
