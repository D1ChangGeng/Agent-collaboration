/** Target integration ports, NOT imports from a stable existing Orca plugin API.
 * Core native links do not convey permission to read/control the native host.
 */
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Address = string;
export type OpaqueCursor = string;
export type EvidenceClass = "native_api" | "authenticated_hook" | "pty_heuristic" | "unknown";
export type Unavailable = { available: false; code: "unsupported" | "host_extension_required" | "unauthorized" | "disconnected"; reason: string };
export type Available<T> = { available: true; value: T };
export type Result<T> = Available<T> | Unavailable;
export interface NativeSessionRef {
  providerRef: string; sessionRef: string; hostRef: string; generation: string;
  authority: "orca" | "harness";
}
export interface SourceLink {
  messageHandle: string; operationId: string; bindingEpoch: number;
  nativeSession: NativeSessionRef; nativeInputRef?: string; nativeTurnRef?: string;
}
export interface NativeRow {
  id: string; revision: number; source: "transcript" | "hook" | "scrape";
  role: "user" | "assistant" | "tool" | "reasoning" | "system";
  // Preserve host-native block schema and provider provenance. No fabricated ACS reply.
  blocks: Json[]; nativeOrder?: string; timestamp: string | null; linkage?: SourceLink;
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
  nativeOperationRef: string; outcome: "accepted" | "refused" | "unknown";
  evidenceRef?: string; reason?: string;
}
export interface NativeViewProvider {
  /** Uses actual host authentication, never an ACS token as a blanket host authorization. */
  capabilities(session: NativeSessionRef): Promise<Result<readonly string[]>>;
  read(session: NativeSessionRef, cursor?: OpaqueCursor): Promise<Result<NativePage>>;
  watch(session: NativeSessionRef, after?: OpaqueCursor, signal?: AbortSignal): AsyncIterable<NativeEvent>;
  act(session: NativeSessionRef, action: NativeAction, requestId: string): Promise<Result<NativeActionReceipt>>;
  reveal(session: NativeSessionRef, resource?: { kind: "file" | "terminal" | "workspace" | "diff"; ref: string }): Promise<Result<{ opened: boolean }>>;
}
export interface CommunicationSend {
  to: Address; content: string; reply_to?: string[];
  activation?: "invoke" | "message_only"; response_mode?: "async" | "sync";
  wait_timeout_seconds?: number; attachment_refs?: string[];
}
export interface CommunicationReceipt {
  messageHandle: string; operationRef: string; duplicate: boolean;
  nativeState: "not_requested" | "pending" | "deferred" | "submitting" | "accepted" | "rejected" | "unknown" | "unsupported" | "superseded";
  explicitReplyHandle: string | null;
}
export interface CommunicationEvent {
  eventId: string; cursor: OpaqueCursor; resourceRef: string | null; revision: number; kind: string; payload: Json;
}
export interface CommunicationClient {
  send(project: string, request: CommunicationSend, idempotencyKey: string): Promise<CommunicationReceipt>;
  readMessage(project: string, handle: string, offset?: number): Promise<Json>;
  snapshot(project: string): Promise<{ snapshotId: string; afterCursor: OpaqueCursor; data: Json }>;
  watch(project: string, after: OpaqueCursor, signal?: AbortSignal): AsyncIterable<CommunicationEvent>;
  markRead(project: string, conversation: string, throughHandle: string, expectedRevision: string, requestId: string): Promise<Json>;
}
export interface CompositeChatState {
  communicationCursor: OpaqueCursor | null;
  nativeCursor: OpaqueCursor | null;
  nativeSession: NativeSessionRef | null;
  sourceLinks: SourceLink[];
  // Never create one global ordering or equate native completion with explicit reply.
}
export interface OrcaReceiverPort {
  describe(receiverRef: string): Promise<Result<Json>>;
  observe(receiverRef: string): Promise<Result<Json>>;
  /** A sealed Core operation; host verifies its own permission and current input owner. */
  admit(command: NativeAdmissionCommand): Promise<Result<NativeAdmissionResult>>;
  reconcile(receiverRef: string, operationId: string): Promise<Result<NativeAdmissionResult>>;
}

/** Additional native data needed by the complete existing UI; owned by the host. */
export interface NativeSessionSummary { session: NativeSessionRef; title: string; updatedAt: string | null; capabilities: string[]; }
export interface NativeStateView {
  revision: string; status: "working" | "idle" | "blocked" | "unknown" | "ended";
  evidenceClass: EvidenceClass; pendingQuestions: Json[]; pendingApprovals: Json[];
  model: string | null; effort: string | null; usage: Json | null;
}
export interface NativeWorkspaceProvider extends NativeViewProvider {
  listSessions(scopeRef: string, cursor?: OpaqueCursor): Promise<Result<{ items: NativeSessionSummary[]; nextCursor: OpaqueCursor | null }>>;
  state(session: NativeSessionRef): Promise<Result<NativeStateView>>;
  readResource(session: NativeSessionRef, resourceRef: string, cursor?: OpaqueCursor): Promise<Result<{ payload: Json; nextCursor: OpaqueCursor | null }>>;
  prepareAttachment(session: NativeSessionRef, acsAttachmentRef: string): Promise<Result<{ nativeAttachmentRef: string }>>;
}
/** Delegates the EXISTING filtered management tools, not a new task management API. */
export interface AcsManagementProvider {
  call(tool: "configure_root" | "configure_team" | "create_route" | "update_route", argumentsFromCurrentCatalog: Json): Promise<Json>;
}

/** JSON transport of the trusted adapter command; reuse existing enrolled receiver signing. */
export interface NativeAdmissionCommand {
  schema_version: "acs-adapter/1"; operation_id: string; receiver_id: string;
  message_handles: string[]; canonical_hash: string; binding_epoch: number;
  provider_generation: string | null; auth_revision: string;
  input_mode: "structured" | "safe_queue" | "terminal_pointer";
  sealed_envelope: { format: string; encoding: "base64"; data: string };
  deadline: string | null;
}
export interface NativeAdmissionResult {
  schema_version: "acs-adapter/1"; operation_id: string;
  outcome: "accepted" | "queued" | "definitively_not_admitted" | "unknown" | "unsupported";
  effect_possible: boolean; evidence_ref: string | null; native_input_ref: string | null;
  binding_epoch: number; provider_generation: string | null; reason_code: string | null;
}
