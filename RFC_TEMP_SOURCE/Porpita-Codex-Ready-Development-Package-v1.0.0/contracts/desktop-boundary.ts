/** Proposed PORPITA integration/view boundaries, not an adopted ACS wire protocol.
 * Prefer existing SDK types and Host interfaces when wiring actual code.
 * No implementation, retry engine, message database or new authorization layer lives here.
 */
export type Reference = string;
export type CommunicationBackend = "acs";
export type MessageOrigin = "actual-client" | "actual-agent";

export interface WorkspaceCommunicationLink {
  readonly workspaceRef: Reference;
  readonly projectId: Reference;
  readonly actorAddress: Reference;
  /** Existing scope/route only when actually selected; no forced Worktree=Route. */
  readonly routeRef?: Reference;
}

export interface NativeSessionLink {
  readonly agentAddress: Reference;
  readonly providerRef: Reference;
  readonly sessionRef: Reference;
  readonly hostRef: Reference;
  readonly generation: Reference;
  /** Keep existing SDK compatibility values; these are not the visible product name. */
  readonly authority: "orca" | "harness";
}

export interface CommunicationSendIntent {
  readonly projectId: Reference;
  readonly to: Reference;
  readonly content: string;
  readonly replyTo?: readonly Reference[];
  readonly attachmentRefs?: readonly Reference[];
  readonly activation: "invoke" | "message_only";
  readonly requestKey: Reference;
  // Deliberately no sender/principal/grant field: actual caller context supplies identity.
}

export interface CommunicationReceiptView {
  readonly messageHandle: Reference;
  readonly operationRef: Reference;
  readonly persisted: true;
  /** Native admission, peer reply and viewer read state must remain distinct. */
  readonly nativeAdmission: "not_requested" | "pending" | "queued" | "accepted" | "not_admitted" | "unknown" | "unavailable";
  readonly explicitReplyHandle?: Reference;
}

export interface ExecutionSourceView {
  readonly messageHandle: Reference;
  readonly originalOperationRef: Reference;
  readonly originalSession: NativeSessionLink;
  readonly nativeInputRef: Reference;
  readonly nativeTurnRef?: Reference;
}

export interface PorpitaCommunicationFacade {
  readonly backend: CommunicationBackend;
  /** Adapt to the existing ACS SDK; do not implement a second protocol. */
  send(intent: CommunicationSendIntent): Promise<CommunicationReceiptView>;
  executionSource(projectId: Reference, messageHandle: Reference): Promise<ExecutionSourceView | null>;
}

export interface ExistingNativeNavigation {
  /** Independently authorized native navigation, not new ACS read/control authority. */
  openExecution(source: ExecutionSourceView): Promise<void>;
}

export interface GroupSendView {
  readonly results: readonly {
    readonly address: Reference;
    readonly outcome: "committed" | "not_sent" | "unknown";
    readonly messageHandle?: Reference;
    readonly operationRef?: Reference;
  }[];
}

/** Existing workflow owns Task/Gate. Store only references here, not message bodies. */
export interface WorkflowMessageReference {
  readonly workflowOperationId: Reference;
  readonly runId?: Reference;
  readonly taskId?: Reference;
  readonly dispatchId?: Reference;
  readonly acsMessageHandle?: Reference;
  readonly notificationState: "pending" | "committed" | "unknown";
}

/** Generic seam: instantiate Command/Admission from existing ACS types at wiring time. */
export interface ExistingHostReceiverSeam<Command, Admission, Observation> {
  observe(receiverRef: Reference): Promise<Observation>;
  admitVerified(command: Command): Promise<Admission>;
  reconcileOriginal(receiverRef: Reference, originalOperationId: Reference): Promise<Admission>;
}
