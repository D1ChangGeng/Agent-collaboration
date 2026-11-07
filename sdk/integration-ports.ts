import type { NativeAdmissionCommand, NativeAdmissionResult, NativeReceipt, SendRequest } from "./client-contracts.ts";
import type { SourceLink as ClientSourceLink } from "./client-contracts.ts";

export type { NativeAdmissionCommand, NativeAdmissionResult } from "./client-contracts.ts";

/** Host integration ports. Implementations must establish their own current host authorization. */
export type Json = null | boolean | number | string | ReadonlyArray<Json> | { readonly [key: string]: Json };
export type Address = string;
export type OpaqueCursor = string;
export type EvidenceClass = "native_api" | "authenticated_hook" | "pty_heuristic" | "unknown";
export type Unavailable = {
  available: false;
  code: "unsupported" | "host_extension_required" | "unauthorized" | "disconnected";
  reason: string;
};
export type Available<T> = { available: true; value: T };
export type Result<T> = Available<T> | Unavailable;

export interface NativeSessionRef {
  providerRef: string;
  sessionRef: string;
  hostRef: string;
  generation: string;
  authority: "orca" | "harness";
}
/** Only a host's actual original handoff evidence can establish this association. */
export type SourceLink = ClientSourceLink;
export interface NativeRow {
  id: string;
  revision: number;
  source: "transcript" | "hook" | "scrape";
  role: "user" | "assistant" | "tool" | "reasoning" | "system";
  blocks: Json[];
  nativeOrder?: string;
  timestamp: string | null;
  linkage?: SourceLink;
}
export interface NativePage { items: NativeRow[]; nextCursor: OpaqueCursor | null; snapshotRef: string; }
export interface NativeEvent { id: string; cursor: OpaqueCursor; session: NativeSessionRef; kind: string; payload: Json; }
export type NativeAction =
  | { kind: "submit_prompt"; text: string; attachmentRefs: string[] }
  | { kind: "stop_turn"; turnRef: string }
  | { kind: "answer_question"; questionRef: string; expectedRevision: string; answer: Json }
  | { kind: "answer_approval"; approvalRef: string; expectedRevision: string; decision: Json }
  | { kind: "update_queued_input"; inputRef: string; expectedRevision: string; text: string }
  | { kind: "cancel_queued_input"; inputRef: string; expectedRevision: string }
  | { kind: "resume" }
  | { kind: "stop_native_task"; nativeTaskRef: string; expectedRevision: string }
  | { kind: "stop_native_subagent"; childSessionRef: string; expectedRevision: string }
  | { kind: "set_model"; modelRef: string; effort?: string }
  | { kind: "compact" }
  | { kind: "clear" };
export interface NativeActionReceipt {
  nativeOperationRef: string;
  outcome: "accepted" | "refused" | "unknown";
  evidenceRef?: string;
  reason?: string;
}
export type NativeRevealResource = { kind: "file" | "terminal" | "workspace" | "diff"; ref: string };
export interface NativeViewProvider {
  capabilities(session: NativeSessionRef): Promise<Result<readonly string[]>>;
  read(session: NativeSessionRef, cursor?: OpaqueCursor): Promise<Result<NativePage>>;
  watch(session: NativeSessionRef, after?: OpaqueCursor, signal?: AbortSignal): AsyncIterable<NativeEvent>;
  act(session: NativeSessionRef, action: NativeAction, requestId: string): Promise<Result<NativeActionReceipt>>;
  reveal(session: NativeSessionRef, resource?: NativeRevealResource): Promise<Result<{ opened: boolean }>>;
}
export interface NativeSessionSummary {
  session: NativeSessionRef; title: string; updatedAt: string | null; capabilities: string[];
}
export interface NativeStateView {
  revision: string;
  status: "working" | "idle" | "blocked" | "unknown" | "ended";
  evidenceClass: EvidenceClass;
  pendingQuestions: Json[];
  pendingApprovals: Json[];
  model: string | null;
  effort: string | null;
  usage: Json | null;
}
export interface NativeWorkspaceProvider extends NativeViewProvider {
  listSessions(scopeRef: string, cursor?: OpaqueCursor): Promise<Result<{ items: NativeSessionSummary[]; nextCursor: OpaqueCursor | null }>>;
  state(session: NativeSessionRef): Promise<Result<NativeStateView>>;
  readResource(session: NativeSessionRef, resourceRef: string, cursor?: OpaqueCursor): Promise<Result<{ payload: Json; nextCursor: OpaqueCursor | null }>>;
  prepareAttachment(session: NativeSessionRef, acsAttachmentRef: string): Promise<Result<{ nativeAttachmentRef: string }>>;
}

export type CommunicationSend = Pick<SendRequest,
  "to" | "content" | "reply_to" | "activation" | "response_mode" | "wait_timeout_seconds" | "attachment_refs">;
export interface CommunicationReceipt {
  messageHandle: string;
  operationRef: string;
  duplicate: boolean;
  nativeState: NativeReceipt["state"];
  explicitReplyHandle: string | null;
}
export interface CommunicationEvent {
  eventId: string; cursor: OpaqueCursor; resourceRef: string | null; revision: number; kind: string; payload: Json;
}
export interface CommunicationSnapshot { snapshotId: string; afterCursor: OpaqueCursor; data: Json; }
export interface CommunicationClient {
  send(project: string, request: CommunicationSend, idempotencyKey: string): Promise<CommunicationReceipt>;
  readMessage(project: string, handle: string, offset?: number): Promise<Json>;
  snapshot(project: string): Promise<CommunicationSnapshot>;
  watch(project: string, after: OpaqueCursor, signal?: AbortSignal): AsyncIterable<CommunicationEvent>;
  markRead(project: string, conversation: string, throughHandle: string, expectedRevision: string, requestId: string): Promise<Json>;
}
export interface CompositeChatState {
  communicationCursor: OpaqueCursor | null;
  nativeCursor: OpaqueCursor | null;
  nativeSession: NativeSessionRef | null;
  sourceLinks: SourceLink[];
}
export interface OrcaReceiverPort {
  describe(receiverRef: string): Promise<Result<Json>>;
  observe(receiverRef: string): Promise<Result<Json>>;
  admit(command: NativeAdmissionCommand): Promise<Result<NativeAdmissionResult>>;
  reconcile(receiverRef: string, operationId: string): Promise<Result<NativeAdmissionResult>>;
}
export type AcsManagementTool = "configure_root" | "configure_team" | "create_route" | "update_route";
/** Delegates current filtered management tools; each delegate retains its real ACL/catalog checks. */
export interface AcsManagementProvider {
  call(tool: AcsManagementTool, argumentsFromCurrentCatalog: Json): Promise<Json>;
}

export type NativeSessionOperation = Exclude<keyof NativeWorkspaceProvider, "listSessions">;
export type NativeAuthorizationDetails =
  | { operation: "capabilities" | "state" }
  | { operation: "read"; cursor?: OpaqueCursor }
  | { operation: "watch"; after?: OpaqueCursor; signal?: AbortSignal }
  | { operation: "act"; action: NativeAction; requestId: string }
  | { operation: "reveal"; resource?: NativeRevealResource }
  | { operation: "readResource"; resourceRef: string; cursor?: OpaqueCursor }
  | { operation: "prepareAttachment"; acsAttachmentRef: string };
/** The host checks its own live credentials, current generation and action permission on every call. */
export type NativeHostAuthorize = (
  session: Readonly<NativeSessionRef>, operation: NativeSessionOperation, details: Readonly<NativeAuthorizationDetails>,
) => Result<void> | Promise<Result<void>>;
export type NativeScopeAuthorize = (
  scopeRef: string, operation: "listSessions",
) => Result<void> | Promise<Result<void>>;
export interface NativeViewProviderOptions {
  /** A trusted host-registry binding, never a NativeLink or caller body treated as authority. */
  session?: NativeSessionRef;
  authorize?: NativeHostAuthorize;
  operations?: Partial<NativeViewProvider>;
}
export interface NativeWorkspaceProviderOptions extends Omit<NativeViewProviderOptions, "operations"> {
  operations?: Partial<NativeWorkspaceProvider>;
  scopeRef?: string;
  authorizeScope?: NativeScopeAuthorize;
}

/** AsyncIterable and management ports lack a Result envelope, so unavailability is an error. */
export class PortOperationUnavailable extends Error {
  readonly operation: string;
  readonly availability: Unavailable;
  readonly code: Unavailable["code"];
  constructor(operation: string, availability: Unavailable) {
    super(availability.reason);
    this.name = "PortOperationUnavailable";
    this.operation = operation;
    this.availability = Object.freeze({ ...availability });
    this.code = availability.code;
  }
}

function unavailable(operation: string, code: Unavailable["code"] = "host_extension_required"): Unavailable {
  return { available: false, code, reason: `${operation}: ${code}` };
}
const sessionFields = ["providerRef", "sessionRef", "hostRef", "generation", "authority"] as const;
function captureSession(value: NativeSessionRef | undefined): Readonly<NativeSessionRef> | undefined {
  if (value === undefined) return undefined;
  if (!value || sessionFields.some(key => typeof value[key] !== "string" || !value[key].length) ||
      (value.authority !== "orca" && value.authority !== "harness")) {
    throw new TypeError("Native session binding requires provider, session, host, generation and authority");
  }
  return Object.freeze({ providerRef: value.providerRef, sessionRef: value.sessionRef, hostRef: value.hostRef,
    generation: value.generation, authority: value.authority });
}
function sameSession(actual: NativeSessionRef, bound: Readonly<NativeSessionRef>): boolean {
  return !!actual && sessionFields.every(key => actual[key] === bound[key]);
}
function denial(value: Result<void>, operation: string): Unavailable | null {
  if (value && value.available === true) return null;
  if (value && value.available === false &&
      ["unsupported", "host_extension_required", "unauthorized", "disconnected"].includes(value.code) &&
      typeof value.reason === "string") return value;
  return unavailable(operation, "unauthorized");
}
/** Preserve the exact action authorized across an asynchronous permission check. */
function frozenCopy<T>(value: T): T {
  const result = structuredClone(value);
  const pending: unknown[] = [result];
  const seen = new WeakSet<object>();
  while (pending.length) {
    const next = pending.pop();
    if (next && typeof next === "object" && !seen.has(next)) {
      seen.add(next);
      for (const child of Object.values(next)) pending.push(child);
      Object.freeze(next);
    }
  }
  return result;
}

/**
 * Creates a session-bound admission wrapper, without host I/O or ACS bearer handling.
 * Method presence conveys no capability. Hosts must still enforce live target ownership
 * at their side-effect boundary; this wrapper does not establish a host registry binding.
 */
export function createNativeWorkspaceProvider(options: NativeWorkspaceProviderOptions = {}): NativeWorkspaceProvider {
  const bound = captureSession(options.session);
  const authorize = options.authorize;
  const scopeRef = options.scopeRef;
  const authorizeScope = options.authorizeScope;
  const operations = options.operations;
  // Capture implementations once; later config mutation cannot replace an admitted operation.
  const capabilities = operations?.capabilities?.bind(operations);
  const read = operations?.read?.bind(operations);
  const watch = operations?.watch?.bind(operations);
  const act = operations?.act?.bind(operations);
  const reveal = operations?.reveal?.bind(operations);
  const listSessions = operations?.listSessions?.bind(operations);
  const state = operations?.state?.bind(operations);
  const readResource = operations?.readResource?.bind(operations);
  const prepareAttachment = operations?.prepareAttachment?.bind(operations);

  async function gate(session: NativeSessionRef, operation: NativeSessionOperation, details: NativeAuthorizationDetails): Promise<Result<Readonly<NativeSessionRef>>> {
    if (!bound || !authorize) return unavailable(operation);
    if (!sameSession(session, bound)) return unavailable(operation, "unauthorized");
    const rejected = denial(await authorize(bound, operation, Object.freeze(details)), operation);
    return rejected ?? { available: true, value: bound };
  }
  async function invoke<T>(session: NativeSessionRef, details: NativeAuthorizationDetails,
    delegate: ((actual: Readonly<NativeSessionRef>) => Promise<Result<T>>) | undefined): Promise<Result<T>> {
    if (!delegate) return unavailable(details.operation);
    const admitted = await gate(session, details.operation, details);
    if (!admitted.available) return admitted;
    const value = await delegate(admitted.value);
    // These operations return Host-private data. Capture it before another
    // asynchronous check so the delegate cannot replace the released value.
    if (["capabilities", "read", "state", "readResource"].includes(details.operation)) {
      const captured = frozenCopy(value);
      const current = await gate(admitted.value, details.operation, details);
      return current.available ? captured : current;
    }
    return value;
  }
  return Object.freeze({
    capabilities(session: NativeSessionRef) {
      return invoke(session, { operation: "capabilities" }, capabilities && (actual => capabilities(actual)));
    },
    read(session: NativeSessionRef, cursor?: OpaqueCursor) {
      return invoke(session, { operation: "read", cursor }, read && (actual => read(actual, cursor)));
    },
    async *watch(session: NativeSessionRef, after?: OpaqueCursor, signal?: AbortSignal): AsyncIterable<NativeEvent> {
      if (!watch) throw new PortOperationUnavailable("watch", unavailable("watch"));
      const admitted = await gate(session, "watch", { operation: "watch", after, signal });
      if (!admitted.available) throw new PortOperationUnavailable("watch", admitted);
      for await (const event of watch(admitted.value, after, signal)) {
        const captured = frozenCopy(event);
        if (!sameSession(captured.session, admitted.value)) {
          throw new PortOperationUnavailable("watch", unavailable("watch", "unauthorized"));
        }
        const current = await gate(admitted.value, "watch", { operation: "watch", after, signal });
        if (!current.available) throw new PortOperationUnavailable("watch", current);
        if (!sameSession(captured.session, current.value)) {
          throw new PortOperationUnavailable("watch", unavailable("watch", "unauthorized"));
        }
        yield captured;
      }
    },
    act(session: NativeSessionRef, action: NativeAction, requestId: string) {
      const captured = frozenCopy(action);
      return invoke(session, { operation: "act", action: captured, requestId }, act && (actual => act(actual, captured, requestId)));
    },
    reveal(session: NativeSessionRef, resource?: NativeRevealResource) {
      const captured = resource === undefined ? undefined : frozenCopy(resource);
      return invoke(session, { operation: "reveal", resource: captured }, reveal && (actual => reveal(actual, captured)));
    },
    async listSessions(scope: string, cursor?: OpaqueCursor) {
      if (!listSessions || !authorizeScope || scopeRef === undefined) return unavailable("listSessions");
      if (scope !== scopeRef) return unavailable("listSessions", "unauthorized");
      const rejected = denial(await authorizeScope(scope, "listSessions"), "listSessions");
      if (rejected) return rejected;
      const captured = frozenCopy(await listSessions(scope, cursor));
      const current = denial(await authorizeScope(scope, "listSessions"), "listSessions");
      return current ?? captured;
    },
    state(session: NativeSessionRef) {
      return invoke(session, { operation: "state" }, state && (actual => state(actual)));
    },
    readResource(session: NativeSessionRef, resourceRef: string, cursor?: OpaqueCursor) {
      return invoke(session, { operation: "readResource", resourceRef, cursor },
        readResource && (actual => readResource(actual, resourceRef, cursor)));
    },
    prepareAttachment(session: NativeSessionRef, acsAttachmentRef: string) {
      return invoke(session, { operation: "prepareAttachment", acsAttachmentRef },
        prepareAttachment && (actual => prepareAttachment(actual, acsAttachmentRef)));
    },
  });
}

/** Clear only the Native view after Host authorization/session loss. ACS replay
 * state belongs to its own authority and is not advanced or reset by this call.
 * Authoritative SourceLink records remain at their owning Host/Core service.
 */
export function invalidateNativeState(state: CompositeChatState): CompositeChatState {
  return { ...state, nativeCursor: null, nativeSession: null, sourceLinks: [] };
}

export function createNativeViewProvider(options: NativeViewProviderOptions = {}): NativeViewProvider {
  const provider = createNativeWorkspaceProvider(options);
  return Object.freeze({ capabilities: provider.capabilities, read: provider.read, watch: provider.watch,
    act: provider.act, reveal: provider.reveal });
}

export type AcsManagementOperations = Partial<Record<AcsManagementTool, (argumentsFromCurrentCatalog: Json) => Json | Promise<Json>>>;
export function createManagementProvider(operations: AcsManagementOperations = {}): AcsManagementProvider {
  const tools: readonly AcsManagementTool[] = ["configure_root", "configure_team", "create_route", "update_route"];
  const admitted = new Map(tools.flatMap(tool => typeof operations[tool] === "function"
    ? [[tool, operations[tool]!.bind(operations)] as const] : []));
  return Object.freeze({
    async call(tool: AcsManagementTool, argumentsFromCurrentCatalog: Json) {
      const delegate = admitted.get(tool);
      if (!delegate) throw new PortOperationUnavailable(tool, unavailable(tool));
      return delegate(argumentsFromCurrentCatalog);
    },
  });
}
