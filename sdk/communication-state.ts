import type {
  Actor, AttachmentRef, Contact, Conversation, DeliveryFacts, Draft, Event as AcsEvent,
  Message, NativeLink, Notice, Preferences, ReadState, Receiver, Snapshot,
} from "./client-contracts.ts";

export type ProjectionPlane = "message" | "delivery" | "contact" | "conversation" | "receiver" |
  "capability" | "notice" | "read_state" | "draft" | "preferences" | "attachment" | "native_link";
export type ProjectionValue = Message | DeliveryFacts | Contact | Conversation | Receiver | Notice |
  ReadState | Draft | Preferences | AttachmentRef | NativeLink;
export type Projection = Readonly<{ revision: number; value: ProjectionValue; stale: boolean; requiredRevision: number | null }>;
export type Invalidation = Readonly<{ kind: AcsEvent["kind"]; revision: number; eventId: string; payload: AcsEvent["payload"] }>;
export type LocalWorkOwner = Readonly<{
  key: string; projectId: string; kind: "slot" | "client" | "address" | "unowned";
  principalRef: string | null; address: string | null; agentSlotId: string | null;
}>;
export type ArchivedLocalWork = Readonly<{
  owner: LocalWorkOwner; localDrafts: ReadonlyMap<string, unknown>; pendingCommands: ReadonlyMap<string, unknown>;
}>;
export class LocalWorkArchiveQuotaError extends Error {
  readonly code = "local_work_archive_quota";
  readonly reason: string;
  constructor(reason: string) {
    super("Local work archive capacity requires explicit caller resolution; state is unchanged");
    this.name = "LocalWorkArchiveQuotaError"; this.reason = reason;
  }
}
export type CommunicationState = Readonly<{
  projectId: string;
  actor: Actor | null;
  authRevision: string | null;
  requiresSnapshot: boolean;
  resetReason: string | null;
  snapshot: Snapshot | null;
  resources: ReadonlyMap<string, Projection>;
  invalidations: ReadonlyMap<string, Invalidation>;
  eventIds: ReadonlyMap<string, true>;
  cursors: Readonly<{ acs: string | null; native: ReadonlyMap<string, string> }>;
  localDrafts: ReadonlyMap<string, unknown>;
  pendingCommands: ReadonlyMap<string, unknown>;
  localWorkOwner: LocalWorkOwner | null;
  archivedLocalWork: ReadonlyMap<string, ArchivedLocalWork>;
  limits: Readonly<{ maxEventIds: number; maxResources: number; maxArchivedOwners: number; maxArchivedBytes: number }>;
}>;

export type CommunicationAction =
  | { type: "snapshot"; snapshot: Snapshot }
  | { type: "event"; event: AcsEvent }
  | { type: "projection"; plane: ProjectionPlane; resourceRef: string; revision: number; value: ProjectionValue; authRevision: string; observedEventId?: string }
  | { type: "localDraft"; conversationId: string; value: unknown }
  | { type: "pendingCommand"; clientRequestId: string; value: unknown }
  | { type: "nativeCursor"; source: string; cursor: string }
  | { type: "invalidate"; reason: string };

const EVENT_KINDS = new Set<AcsEvent["kind"]>([
  "message.committed", "reply.linked", "delivery.changed", "receiver.observed", "capability.changed",
  "notice.created", "notice.updated", "conversation.updated", "read_state.changed", "draft.changed",
  "attachment.ready", "native_link.changed", "permission.changed", "resync.required", "stream.end",
]);
const PLANES = new Set<ProjectionPlane>(["message", "delivery", "contact", "conversation", "receiver", "capability",
  "notice", "read_state", "draft", "preferences", "attachment", "native_link"]);
const comparable = new Set<ProjectionPlane>(["message", "delivery", "read_state", "draft"]);
const eventFields = new Set(["schema_version", "event_id", "cursor", "project_id", "kind", "resource_ref",
  "resource_revision", "committed_at", "auth_revision", "payload"]);
const payloadFields = new Set(["reason_code", "message_handle", "conversation_id", "operation_ref", "reset_required"]);

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function reference(value: unknown, maximum = 512): value is string {
  // Admitted JSON Schema and Runtime strings count Unicode characters; wire
  // and archive budgets are separately measured in UTF-8 bytes.
  return typeof value === "string" && value.length > 0 && [...value].length <= maximum && !/[\r\n\0]/.test(value);
}
function revision(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}
function timestamp(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
}
function copy<T>(value: T): T {
  return structuredClone(value);
}

/** Runtime envelope validation; Event payloads contain metadata, never DTOs/journals. */
export function validateCommunicationEvent(value: unknown): AcsEvent {
  if (!record(value) || Object.keys(value).length !== eventFields.size || Object.keys(value).some(key => !eventFields.has(key)) ||
      value.schema_version !== "acs-event/1" || !reference(value.event_id) || !reference(value.cursor, 2048) ||
      !reference(value.project_id) || !EVENT_KINDS.has(value.kind as AcsEvent["kind"]) ||
      !(value.resource_ref === null || reference(value.resource_ref)) || !revision(value.resource_revision) ||
      !timestamp(value.committed_at) || !reference(value.auth_revision) || !record(value.payload) ||
      Object.keys(value.payload).some(key => !payloadFields.has(key)) ||
      new TextEncoder().encode(JSON.stringify(value.payload)).byteLength > 8192 ||
      Object.entries(value.payload).some(([key, item]) => key === "reset_required" ? typeof item !== "boolean" :
        key === "reason_code" ? typeof item !== "string" : !reference(item))) {
    throw new TypeError("Invalid ACS event envelope");
  }
  return copy(value) as AcsEvent;
}

export function projectionKey(plane: ProjectionPlane, resourceRef: string): string {
  if (!PLANES.has(plane) || !reference(resourceRef)) throw new TypeError("Invalid projection identity");
  return JSON.stringify([plane, resourceRef]);
}

export function createCommunicationState(projectId: string, options: {
  maxEventIds?: number; maxResources?: number; maxArchivedOwners?: number; maxArchivedBytes?: number;
} = {}): CommunicationState {
  const maxEventIds = options.maxEventIds ?? 1024;
  const maxResources = options.maxResources ?? 4096;
  const maxArchivedOwners = options.maxArchivedOwners ?? 8;
  const maxArchivedBytes = options.maxArchivedBytes ?? 4 * 1024 * 1024;
  if (!reference(projectId) || !Number.isSafeInteger(maxEventIds) || maxEventIds < 1 || maxEventIds > 4096 ||
      !Number.isSafeInteger(maxResources) || maxResources < 1 || maxResources > 16384 ||
      !Number.isSafeInteger(maxArchivedOwners) || maxArchivedOwners < 0 || maxArchivedOwners > 64 ||
      !Number.isSafeInteger(maxArchivedBytes) || maxArchivedBytes < 256 || maxArchivedBytes > 64 * 1024 * 1024) {
    throw new TypeError("Invalid communication state limits");
  }
  return { projectId, actor: null, authRevision: null, requiresSnapshot: true, resetReason: "initial_snapshot_required", snapshot: null,
    resources: new Map(), invalidations: new Map(), eventIds: new Map(), cursors: { acs: null, native: new Map() },
    localDrafts: new Map(), pendingCommands: new Map(), localWorkOwner: null, archivedLocalWork: new Map(),
    limits: { maxEventIds, maxResources, maxArchivedOwners, maxArchivedBytes } };
}

function viewerOwner(projectId: string, actor: Actor): LocalWorkOwner {
  if (!reference(actor.principal_ref) || !reference(actor.address) ||
      !(actor.agent_slot_id === null || reference(actor.agent_slot_id)) ||
      !["client", "root", "route", "agent"].includes(actor.level)) throw new TypeError("Invalid snapshot viewer identity");
  const kind = actor.agent_slot_id !== null ? "slot" : actor.level === "client" ? "client" : "address";
  const identity = actor.agent_slot_id ?? actor.address;
  return { key: JSON.stringify(["local-work", projectId, actor.principal_ref, kind, identity]), projectId, kind,
    principalRef: actor.principal_ref, address: actor.address, agentSlotId: actor.agent_slot_id };
}

function unownedWork(projectId: string): LocalWorkOwner {
  return { key: JSON.stringify(["local-work", "unowned", projectId]), projectId, kind: "unowned",
    principalRef: null, address: null, agentSlotId: null };
}

function localWorkForViewer(state: CommunicationState, owner: LocalWorkOwner): Pick<CommunicationState,
  "localWorkOwner" | "localDrafts" | "pendingCommands" | "archivedLocalWork"> {
  if (state.localWorkOwner?.key === owner.key) {
    return { localWorkOwner: owner, localDrafts: state.localDrafts, pendingCommands: state.pendingCommands,
      archivedLocalWork: state.archivedLocalWork };
  }
  const archivedLocalWork = new Map(state.archivedLocalWork);
  const restored = archivedLocalWork.get(owner.key);
  archivedLocalWork.delete(owner.key); // Restore to active work, never transfer to a different viewer.
  if (state.localDrafts.size || state.pendingCommands.size) {
    const previous = state.localWorkOwner ?? unownedWork(state.projectId);
    if (archivedLocalWork.has(previous.key)) throw new LocalWorkArchiveQuotaError("duplicate_owner_bucket");
    archivedLocalWork.set(previous.key, { owner: previous, localDrafts: state.localDrafts, pendingCommands: state.pendingCommands });
  }
  if (archivedLocalWork.size > state.limits.maxArchivedOwners) throw new LocalWorkArchiveQuotaError("owner_limit");
  let encoded: string;
  try {
    encoded = JSON.stringify([...archivedLocalWork.values()].map(item => ({ owner: item.owner,
      localDrafts: [...item.localDrafts], pendingCommands: [...item.pendingCommands] })));
  } catch { throw new LocalWorkArchiveQuotaError("unserializable_archive_value"); }
  if (new TextEncoder().encode(encoded).byteLength > state.limits.maxArchivedBytes) throw new LocalWorkArchiveQuotaError("byte_limit");
  return { localWorkOwner: owner, localDrafts: restored?.localDrafts ?? new Map(), pendingCommands: restored?.pendingCommands ?? new Map(), archivedLocalWork };
}

function invalidate(state: CommunicationState, reason: string): CommunicationState {
  return { ...state, actor: null, authRevision: null, requiresSnapshot: true, resetReason: reason, snapshot: null,
    resources: new Map(), invalidations: new Map(), eventIds: new Map(), cursors: { acs: null, native: new Map() } };
}

function eventPlane(kind: AcsEvent["kind"]): ProjectionPlane | null {
  switch (kind) {
    case "message.committed": case "reply.linked": return "message";
    case "delivery.changed": return "delivery";
    case "read_state.changed": return "read_state";
    case "draft.changed": return "draft";
    case "receiver.observed": return "receiver";
    case "capability.changed": return "capability";
    case "notice.created": case "notice.updated": return "notice";
    case "conversation.updated": return "conversation";
    case "attachment.ready": return "attachment";
    case "native_link.changed": return "native_link";
    default: return null;
  }
}

function seed(resources: Map<string, Projection>, plane: ProjectionPlane, ref: string, value: ProjectionValue & { revision: number }): void {
  if (!revision(value.revision)) throw new TypeError("Invalid snapshot resource revision");
  const key = projectionKey(plane, ref);
  const previous = resources.get(key);
  if (!previous || value.revision > previous.revision) resources.set(key, { revision: value.revision, value: copy(value), stale: false, requiredRevision: null });
}

/** Pure state transitions. Calling this reducer never executes a pending command. */
export function reduceCommunication(state: CommunicationState, action: CommunicationAction): CommunicationState {
  switch (action.type) {
    case "invalidate": return invalidate(state, action.reason);
    case "localDraft": {
      if (!reference(action.conversationId)) throw new TypeError("Invalid local draft identity");
      const localDrafts = new Map(state.localDrafts); localDrafts.set(action.conversationId, copy(action.value));
      return { ...state, localDrafts };
    }
    case "pendingCommand": {
      if (!reference(action.clientRequestId)) throw new TypeError("Invalid pending request identity");
      const pendingCommands = new Map(state.pendingCommands); pendingCommands.set(action.clientRequestId, copy(action.value));
      return { ...state, pendingCommands };
    }
    case "nativeCursor": {
      if (!reference(action.source) || !reference(action.cursor, 2048)) throw new TypeError("Invalid Native cursor");
      if (state.requiresSnapshot) return state;
      const native = new Map(state.cursors.native); native.set(action.source, action.cursor);
      return { ...state, cursors: { ...state.cursors, native } };
    }
    case "snapshot": {
      // A live stream cannot be rewound by an older snapshot. Refresh/reset is
      // explicit; fresh snapshots are fetched and authorized by the caller.
      if (!state.requiresSnapshot) return state;
      const snapshot = action.snapshot;
      if (!reference(snapshot.snapshot_id) || !reference(snapshot.after_cursor, 2048) || !reference(snapshot.auth_revision) ||
          !timestamp(snapshot.snapshot_expires_at) || Date.parse(snapshot.snapshot_expires_at) <= Date.now() ||
          !record(snapshot.actor) || !Array.isArray(snapshot.contacts) || !Array.isArray(snapshot.conversations) ||
          !Array.isArray(snapshot.receivers) || !revision(snapshot.notice_count) ||
          snapshot.conversations.some(item => item.project_id !== state.projectId)) throw new TypeError("Invalid or expired ACS snapshot");
      const resources = new Map<string, Projection>();
      for (const item of snapshot.contacts) seed(resources, "contact", item.address, item);
      for (const item of snapshot.conversations) seed(resources, "conversation", item.conversation_id, item);
      for (const item of snapshot.receivers) seed(resources, "receiver", item.receiver_id, item);
      if (resources.size > state.limits.maxResources) return invalidate(state, "cache_capacity_exceeded");
      const localWork = localWorkForViewer(state, viewerOwner(state.projectId, snapshot.actor));
      return { ...state, actor: copy(snapshot.actor), authRevision: snapshot.auth_revision, requiresSnapshot: false, resetReason: null,
        snapshot: copy(snapshot), resources, invalidations: new Map(), eventIds: new Map(), cursors: { acs: snapshot.after_cursor, native: new Map() }, ...localWork };
    }
    case "projection": {
      if (state.requiresSnapshot) return state;
      if (action.authRevision !== state.authRevision) return invalidate(state, "authorization_changed");
      if (!revision(action.revision)) throw new TypeError("Invalid projection revision");
      if (record(action.value) && "revision" in action.value && action.value.revision !== action.revision) {
        throw new TypeError("Projection value and owning revision differ");
      }
      if (record(action.value) && "project_id" in action.value && action.value.project_id !== state.projectId) {
        throw new TypeError("Projection belongs to another project");
      }
      const key = projectionKey(action.plane, action.resourceRef);
      const previous = state.resources.get(key);
      if (previous && action.revision < previous.revision) return state;
      if (previous && action.revision === previous.revision) {
        const signal = state.invalidations.get(key);
        if (previous.stale && !comparable.has(action.plane) && signal && action.observedEventId === signal.eventId) {
          const resources = new Map(state.resources);
          resources.set(key, { revision: action.revision, value: copy(action.value), stale: false, requiredRevision: null });
          return { ...state, resources };
        }
        return state;
      }
      const resources = new Map(state.resources);
      const requiredRevision = previous?.requiredRevision ?? null;
      const invalidation = state.invalidations.get(key);
      const required = comparable.has(action.plane) ? Math.max(requiredRevision ?? 0, invalidation?.revision ?? 0) : null;
      const unacknowledged = !comparable.has(action.plane) && invalidation !== undefined && action.observedEventId !== invalidation.eventId;
      resources.set(key, { revision: action.revision, value: copy(action.value), stale: unacknowledged || required !== null && action.revision < required,
        requiredRevision: required !== null && action.revision < required ? required : null });
      if (resources.size + state.invalidations.size > state.limits.maxResources) return invalidate(state, "cache_capacity_exceeded");
      return { ...state, resources };
    }
    case "event": {
      const event = validateCommunicationEvent(action.event);
      if (event.project_id !== state.projectId) throw new TypeError("Event belongs to another project");
      if (event.kind === "permission.changed" || event.kind === "resync.required" || event.payload.reset_required === true) {
        return invalidate(state, event.payload.reason_code ?? event.kind);
      }
      if (state.requiresSnapshot) return state;
      if (event.auth_revision !== state.authRevision) return invalidate(state, "authorization_changed");
      const eventIds = new Map(state.eventIds);
      if (eventIds.has(event.event_id)) {
        eventIds.delete(event.event_id); eventIds.set(event.event_id, true);
        return { ...state, eventIds }; // An old duplicate's opaque cursor cannot rewind the stream.
      }
      eventIds.set(event.event_id, true);
      if (eventIds.size > state.limits.maxEventIds) eventIds.delete(eventIds.keys().next().value!);
      const invalidations = new Map(state.invalidations);
      const resources = new Map(state.resources);
      const plane = eventPlane(event.kind);
      let stale = false;
      if (plane && event.resource_ref !== null) {
        const key = projectionKey(plane, event.resource_ref);
        const old = invalidations.get(key);
        stale = old !== undefined && event.resource_revision <= old.revision;
        if (!old || event.resource_revision > old.revision) {
          invalidations.set(key, { kind: event.kind, revision: event.resource_revision, eventId: event.event_id, payload: copy(event.payload) });
          const value = resources.get(key);
          if (value && (!comparable.has(plane) || event.resource_revision > value.revision)) {
            resources.set(key, { ...value, stale: true,
              requiredRevision: comparable.has(plane) ? Math.max(value.requiredRevision ?? 0, event.resource_revision) : null });
          }
        }
      }
      if (resources.size + invalidations.size > state.limits.maxResources) return invalidate(state, "cache_capacity_exceeded");
      return { ...state, eventIds, resources, invalidations, cursors: { ...state.cursors, acs: stale ? state.cursors.acs : event.cursor } };
    }
    default: throw new TypeError("Unknown communication state action");
  }
}
