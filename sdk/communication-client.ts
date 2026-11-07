import type * as DTO from "./client-contracts.ts";
import type { ClientModelName, ClientModels } from "./client-runtime-schema.ts";
import { ClientContractError, parseClientJson, validateClientModel } from "./client-validation.ts";
import { CommunicationHttpError, CommunicationHttpTransport, reference, requestKey, resourceUrl, sealJson } from "./communication-http.ts";
import type { HttpOptions, HttpRequest } from "./communication-http.ts";
import { CommunicationEventStream, SnapshotRequiredError } from "./communication-stream.ts";
import type { StreamLimits } from "./communication-stream.ts";
import type { CommunicationClient, CommunicationEvent, Json } from "./integration-ports.ts";

export type RequestOptions = { signal?: AbortSignal };
export type PageOptions = RequestOptions & { limit?: number; cursor?: string; snapshotId?: string };
export type WriteOptions = RequestOptions & { expectedRevision: string | number; requestId: string };
export type CompleteMessage = Readonly<{ first: DTO.ReadMessageResponse; text: string; bytes: Uint8Array }>;
export type BinaryInput = Uint8Array | Blob;
export type DownloadedAttachment = Readonly<{ attachment: DTO.Attachment; bytes: Uint8Array }>;
export type CommunicationClientOptions = HttpOptions & { maxAttachmentBytes?: number; maxCompleteMessageBytes?: number; maxBodyPages?: number };
const encoder = new TextEncoder();
function bounded(value: number, maximum: number): number {
  if (!Number.isSafeInteger(value) || value < 1 || value > maximum) throw new TypeError("Invalid ACS byte/page bound");
  return value;
}
function projectIdentity(value: unknown, project: string): void {
  if (!value || typeof value !== "object") return;
  if ("project_id" in value && value.project_id !== project) throw new ClientContractError("project_identity");
  for (const family of ["items", "conversations"]) {
    if (family in value) {
      const children: unknown = Reflect.get(value, family);
      if (Array.isArray(children)) for (const child of children) projectIdentity(child, project);
    }
  }
}
function pageQuery(options: PageOptions) {
  if (options.limit !== undefined) bounded(options.limit, 100);
  return { limit: options.limit, cursor: options.cursor, snapshot_id: options.snapshotId };
}
function pageIdentity(value: unknown, snapshotId: unknown): void {
  if (snapshotId !== undefined && snapshotId !== null && value !== null && typeof value === "object" && "page" in value) {
    const page = value.page;
    if (page === null || typeof page !== "object" || !("snapshot_id" in page) || page.snapshot_id !== snapshotId) throw new ClientContractError("page_snapshot_identity");
  }
}
async function sha256(bytes: Uint8Array): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new CommunicationHttpError("capability_unsupported");
  const owned = new Uint8Array(bytes.byteLength); owned.set(bytes);
  return [...new Uint8Array(await globalThis.crypto.subtle.digest("SHA-256", owned))].map(value => value.toString(16).padStart(2, "0")).join("");
}
function jsonValue(value: unknown): Json {
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number" && Number.isFinite(value)) return value;
  if (Array.isArray(value)) return value.map(jsonValue);
  if (value && typeof value === "object") {
    const result: Record<string, Json> = {};
    for (const [key, child] of Object.entries(value)) Object.defineProperty(result, key, { value: jsonValue(child), enumerable: true });
    return result;
  }
  throw new ClientContractError("JSON");
}

/** One caller-owned HTTP session. close() fences outstanding responses on an owner change.
 * No pending-command storage, credential refresh retry, automatic resend or host authorization.
 */
export class HttpCommunicationClient {
  private http: CommunicationHttpTransport;
  private maximumFile: number;
  private maximumMessage: number;
  private maximumPages: number;
  private fetcher: typeof globalThis.fetch;
  private streams = new Set<AbortController>();
  private snapshotAuth = new Map<string, string>();
  private snapshotOwners = new Map<string, string>();
  private contextVersion = 0;
  constructor(options: CommunicationClientOptions) {
    this.http = new CommunicationHttpTransport(options);
    this.fetcher = options.fetch ?? globalThis.fetch;
    this.maximumFile = bounded(options.maxAttachmentBytes ?? 20 * 1024 * 1024, 256 * 1024 * 1024);
    this.maximumMessage = bounded(options.maxCompleteMessageBytes ?? 1024 * 1024, 32 * 1024 * 1024);
    this.maximumPages = bounded(options.maxBodyPages ?? 65536, 100000);
  }
  close(): void {
    this.resetContext(); this.http.close();
  }
  private resetContext(): void {
    this.contextVersion++; this.http.advanceContext();
    for (const stream of this.streams) stream.abort(); this.streams.clear(); this.snapshotAuth.clear(); this.snapshotOwners.clear();
  }
  private checkContext(version: number, effectState: "none" | "committed" = "none"): void {
    if (version !== this.contextVersion) throw new CommunicationHttpError("authorization_changed", { effectState });
  }
  private guarded<T>(promise: Promise<T>, context: number, mutating = false): Promise<T> {
    return promise.then(value => { this.checkContext(context, mutating ? "committed" : "none"); return value; }).catch(error => {
      if (context === this.contextVersion && error instanceof CommunicationHttpError && error.requiresSnapshot) this.resetContext();
      throw error;
    });
  }
  private global<N extends ClientModelName>(model: N, segments: readonly string[], options: RequestOptions = {}): Promise<ClientModels[N]> {
    return this.guarded(this.http.json(model, { segments, signal: options.signal }), this.contextVersion);
  }
  private scoped<N extends ClientModelName>(model: N, project: string, tail: readonly string[], input: Omit<HttpRequest, "segments"> = {},
      verify?: (value: ClientModels[N]) => void): Promise<ClientModels[N]> {
    const ownProject = reference(project), context = this.contextVersion, snapshotId = input.query?.snapshot_id;
    const method = input.method ?? "GET", mutating = input.mutating ?? method !== "GET";
    return this.guarded(this.http.json(model, { ...input, segments: ["projects", ownProject, ...tail] }, value => {
      projectIdentity(value, ownProject); pageIdentity(value, snapshotId); verify?.(value);
    }), context, mutating);
  }
  meta(options: RequestOptions = {}) { return this.global("Meta", ["meta"], options); }
  profile(options: RequestOptions = {}) { return this.global("Actor", ["profile"], options); }
  projects(options: PageOptions = {}) {
    const query = pageQuery(options), context = this.contextVersion;
    return this.guarded(this.http.json("ProjectPage", { segments: ["projects"], query, signal: options.signal }, value => pageIdentity(value, query.snapshot_id)), context);
  }
  routes(project: string, options: PageOptions = {}) { return this.scoped("RoutePage", project, ["routes"], { query: pageQuery(options), signal: options.signal }); }
  contacts(project: string, options: PageOptions & { name?: string; scopeHandle?: string } = {}) {
    return this.scoped("ContactPage", project, ["contacts"], { query: { ...pageQuery(options), name: options.name, scope_handle: options.scopeHandle }, signal: options.signal });
  }
  conversations(project: string, options: PageOptions & { includeArchived?: boolean } = {}) {
    return this.scoped("ConversationPage", project, ["conversations"], { query: { ...pageQuery(options), include_archived: options.includeArchived }, signal: options.signal });
  }
  resolveConversation(project: string, peer: string, options: RequestOptions = {}) {
    return this.scoped("Conversation", project, ["conversations", "resolve"], { query: { with: reference(peer) }, signal: options.signal });
  }
  conversation(project: string, conversation: string, options: RequestOptions = {}) { return this.scoped("Conversation", project, ["conversations", reference(conversation)], { signal: options.signal }); }
  messages(project: string, options: PageOptions & { peer?: string; conversationId?: string; replyRoot?: string; direction?: "both" | "incoming" | "outgoing" } = {}) {
    return this.scoped("MessagePage", project, ["messages"], { query: { ...pageQuery(options), with: options.peer, conversation_id: options.conversationId, reply_root: options.replyRoot, direction: options.direction }, signal: options.signal });
  }
  readMessage(project: string, handle: string, options: RequestOptions & { offset?: number; maxInlineBytes?: number; includeNativeSource?: boolean } = {}) {
    const selected = reference(handle);
    const offset = options.offset ?? 0, maximum = options.maxInlineBytes;
    if (!Number.isSafeInteger(offset) || offset < 0) throw new TypeError("Invalid body byte offset");
    if (maximum !== undefined) bounded(maximum, 65536);
    if (options.includeNativeSource !== undefined && typeof options.includeNativeSource !== "boolean") throw new TypeError("Invalid Native provenance selection");
    return this.scoped("ReadMessageResponse", project, ["messages", selected], { query: { offset, max_inline_bytes: maximum,
      include_native_source: options.includeNativeSource || undefined }, signal: options.signal }, result => {
      const message = result.message;
      projectIdentity(message, project); if (message.message_handle !== selected || message.content.offset !== offset) throw new ClientContractError("message_identity");
      if (result.first_reply) {
        projectIdentity(result.first_reply, project);
        if (result.first_reply.message_handle !== message.first_reply_handle) throw new ClientContractError("reply_identity");
      } else if (message.first_reply_handle !== null) throw new ClientContractError("reply_identity");
      if (options.includeNativeSource && !result.native_source) throw new ClientContractError("native_source_missing");
      if (result.native_source?.available && result.native_source.value.messageHandle !== selected) throw new ClientContractError("native_source_identity");
    });
  }
  async readMessageComplete(project: string, handle: string, options: RequestOptions & { maxBytes?: number; maxInlineBytes?: number; maxPages?: number } = {}): Promise<CompleteMessage> {
    const context = this.contextVersion;
    const selectedProject = reference(project), selected = reference(handle), signal = options.signal;
    const maximum = bounded(options.maxBytes ?? this.maximumMessage, 32 * 1024 * 1024), pages = bounded(options.maxPages ?? this.maximumPages, 100000);
    const inline = bounded(options.maxInlineBytes ?? 16384, 65536);
    let offset = 0, total = 0, digest = "", first: DTO.ReadMessageResponse | undefined;
    const chunks: Uint8Array[] = []; let received = 0;
    for (let count = 0; count < pages; count++) {
      this.checkContext(context);
      const result = await this.readMessage(selectedProject, selected, { offset, maxInlineBytes: inline, signal });
      this.checkContext(context);
      const body = result.message.content;
      if (!first) { first = result; total = body.total_bytes; digest = body.digest; if (total > maximum) throw new ClientContractError("body_size"); }
      if (body.total_bytes !== total || body.digest !== digest || result.message.sender !== first.message.sender || result.message.to !== first.message.to) throw new ClientContractError("body_identity");
      const bytes = encoder.encode(body.text); received += bytes.byteLength;
      if (received > maximum || offset + bytes.byteLength > total) throw new ClientContractError("body_size");
      chunks.push(bytes);
      if (body.next_offset === null) {
        if (offset + bytes.byteLength !== total || received !== total) throw new ClientContractError("body_incomplete");
        const complete = new Uint8Array(received); let position = 0;
        for (const chunk of chunks) { complete.set(chunk, position); position += chunk.byteLength; }
        const actualDigest = await sha256(complete);
        this.checkContext(context);
        if (actualDigest !== digest) throw new ClientContractError("body_digest");
        return { first, text: new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(complete), bytes: complete };
      }
      if (!bytes.byteLength || body.next_offset !== offset + bytes.byteLength || body.next_offset <= offset || body.next_offset >= total) throw new ClientContractError("body_progress");
      offset = body.next_offset;
    }
    throw new ClientContractError("body_page_budget");
  }
  delivery(project: string, handle: string, options: RequestOptions = {}) {
    const selected = reference(handle);
    return this.scoped("DeliveryFacts", project, ["messages", selected, "delivery"], { signal: options.signal }, value => {
      if (value.message_handle !== selected) throw new ClientContractError("delivery_identity");
    });
  }
  search(project: string, query: string, options: PageOptions & { peer?: string; conversationId?: string } = {}) {
    return this.scoped("SearchHitPage", project, ["search"], { query: { ...pageQuery(options), q: query, with: options.peer, conversation_id: options.conversationId }, signal: options.signal });
  }
  async snapshotView(project: string, options: RequestOptions & { limit?: number } = {}): Promise<DTO.Snapshot> {
    const selected = reference(project), context = this.contextVersion;
    const captured = await this.scoped("Snapshot", selected, ["snapshot"], { query: { limit: options.limit }, signal: options.signal }, value => {
      if (value.actor.auth_revision !== value.auth_revision || Date.parse(value.snapshot_expires_at) <= Date.now()) throw new ClientContractError("snapshot_identity");
    });
    this.checkContext(context);
    const owner = JSON.stringify([selected, captured.actor.principal_ref, captured.actor.agent_slot_id, captured.actor.agent_slot_id === null ? captured.actor.address : null]);
    if (this.snapshotAuth.get(selected) !== captured.auth_revision || this.snapshotOwners.get(selected) !== owner) {
      this.resetContext();
    }
    this.snapshotOwners.set(selected, owner);
    this.snapshotAuth.set(selected, captured.auth_revision); return captured;
  }
  receivers(project: string, options: PageOptions = {}) { return this.scoped("ReceiverPage", project, ["receivers"], { query: pageQuery(options), signal: options.signal }); }
  receiver(project: string, receiver: string, options: RequestOptions = {}) { return this.scoped("Receiver", project, ["receivers", reference(receiver)], { signal: options.signal }); }
  recoverReceiver(project: string, receiver: string, body: DTO.RecoveryRequest, idempotencyKey: string, options: RequestOptions = {}): Promise<DTO.Operation> {
    const selected = reference(receiver), sealed = sealJson("RecoveryRequest", body);
    const declaration = validateClientModel("RecoveryRequest", parseClientJson(sealed));
    if (!declaration.reason.trim()) throw new ClientContractError("recovery_reason");
    return this.scoped("Operation", project, ["receivers", selected, "actions"],
      { method: "POST", body: sealed, key: idempotencyKey, contentType: "application/json", signal: options.signal }, value => {
        if (value.kind !== "recovery" || value.receiver_ref !== selected || value.binding_epoch !== declaration.expected_revision) {
          throw new ClientContractError("recovery_identity");
        }
      });
  }
  nativeLinks(project: string, options: PageOptions & { address?: string } = {}): Promise<DTO.NativeLinkPage> {
    const address = options.address === undefined ? undefined : reference(options.address);
    return this.scoped("NativeLinkPage", project, ["native-links"],
      { query: { ...pageQuery(options), address }, signal: options.signal }, value => {
        if (address !== undefined && value.items.some(item => item.address !== address)) throw new ClientContractError("native_link_address");
      });
  }
  writeNativeLink(project: string, link: string, body: DTO.NativeLinkWrite, idempotencyKey: string, options: RequestOptions = {}): Promise<DTO.NativeLink> {
    const selected = reference(link), sealed = sealJson("NativeLinkWrite", body);
    const declaration = validateClientModel("NativeLinkWrite", parseClientJson(sealed));
    // This is Core association metadata. Host transcript/action authority is
    // independently supplied to the NativeViewProvider integration port.
    return this.scoped("NativeLink", project, ["native-links", selected],
      { method: "PUT", body: sealed, key: idempotencyKey, contentType: "application/json", signal: options.signal }, value => {
        if (value.link_id !== selected || value.address !== declaration.address || value.receiver_ref !== declaration.receiver_ref ||
            value.binding_epoch !== declaration.expected_binding_epoch || value.provider_ref !== declaration.provider_ref ||
            value.native_session_ref !== declaration.native_session_ref || value.native_authority !== declaration.native_authority ||
            value.host_ref !== declaration.expected_host_ref || value.provider_generation !== declaration.expected_provider_generation) {
          throw new ClientContractError("native_link_identity");
        }
      });
  }
  notices(project: string, options: PageOptions = {}) { return this.scoped("NoticePage", project, ["notices"], { query: pageQuery(options), signal: options.signal }); }
  markSeen(project: string, notice: string, body: DTO.SeenWrite, options: WriteOptions) {
    const sealed = sealJson("SeenWrite", body);
    return this.scoped("Notice", project, ["notices", reference(notice), "seen"], { method: "PUT", key: options.requestId, revision: options.expectedRevision, body: sealed, contentType: "application/json", signal: options.signal });
  }
  readState(project: string, conversation: string, options: RequestOptions = {}) { return this.scoped("ReadState", project, ["conversations", reference(conversation), "read-state"], { signal: options.signal }); }
  markRead(project: string, conversation: string, body: DTO.ReadStateWrite, options: WriteOptions) {
    const sealed = sealJson("ReadStateWrite", body);
    return this.scoped("ReadState", project, ["conversations", reference(conversation), "read-state"], { method: "PUT", key: options.requestId, revision: options.expectedRevision, body: sealed, contentType: "application/json", signal: options.signal });
  }
  preferences(project: string, conversation: string, options: RequestOptions = {}) { return this.scoped("Preferences", project, ["conversations", reference(conversation), "preferences"], { signal: options.signal }); }
  updatePreferences(project: string, conversation: string, body: DTO.PreferencesWrite, options: WriteOptions) {
    const sealed = sealJson("PreferencesWrite", body);
    return this.scoped("Preferences", project, ["conversations", reference(conversation), "preferences"], { method: "PUT", key: options.requestId, revision: options.expectedRevision, body: sealed, contentType: "application/json", signal: options.signal });
  }
  draft(project: string, conversation: string, options: RequestOptions = {}) { return this.scoped("Draft", project, ["conversations", reference(conversation), "draft"], { signal: options.signal }); }
  updateDraft(project: string, conversation: string, body: DTO.DraftWrite, options: WriteOptions) {
    const sealed = sealJson("DraftWrite", body);
    return this.scoped("Draft", project, ["conversations", reference(conversation), "draft"], { method: "PUT", key: options.requestId, revision: options.expectedRevision, body: sealed, contentType: "application/json", signal: options.signal });
  }
  deleteDraft(project: string, conversation: string, options: WriteOptions) {
    return this.scoped("Draft", project, ["conversations", reference(conversation), "draft"], { method: "DELETE", key: options.requestId, revision: options.expectedRevision, signal: options.signal });
  }
  wait(project: string, body: DTO.WaitRequest, options: RequestOptions = {}) {
    return this.scoped("WaitResponse", project, ["waits"], { method: "POST", body: sealJson("WaitRequest", body), contentType: "application/json", mutating: false, signal: options.signal });
  }
  operation(project: string, operation: string, options: RequestOptions = {}) {
    const selected = reference(operation);
    return this.scoped("Operation", project, ["operations", selected], { signal: options.signal }, value => {
      if (value.operation_id !== selected) throw new ClientContractError("operation_identity");
    });
  }
  sendMessage(project: string, body: DTO.SendRequest, idempotencyKey: string, options: RequestOptions = {}) {
    const sealed = sealJson("SendRequest", body);
    return this.scoped("SendResponse", project, ["messages"], { method: "POST", body: sealed, key: idempotencyKey, contentType: "application/json", signal: options.signal }, result => {
      projectIdentity(result.message, project);
      if (result.delivery.message_handle !== result.message.message_handle) throw new ClientContractError("delivery_identity");
    });
  }
  reserveAttachment(project: string, body: DTO.AttachmentCreate, idempotencyKey: string, options: RequestOptions = {}) {
    const sealed = sealJson("AttachmentCreate", body);
    const declaration = validateClientModel("AttachmentCreate", parseClientJson(sealed));
    return this.scoped("Attachment", project, ["attachments"], { method: "POST", body: sealed, key: idempotencyKey, contentType: "application/json", signal: options.signal }, value => {
      if (value.bytes !== declaration.bytes || value.sha256 !== declaration.sha256 || value.name !== declaration.name ||
          value.media_type !== declaration.media_type.split(";", 1)[0].trim().toLowerCase()) throw new ClientContractError("attachment_identity");
    });
  }
  attachment(project: string, attachment: string, options: RequestOptions = {}) { return this.scoped("Attachment", project, ["attachments", reference(attachment)], { signal: options.signal }, value => {
    if (value.attachment_id !== attachment) throw new ClientContractError("attachment_identity");
  }); }
  async uploadAttachment(project: string, reservation: DTO.Attachment, content: BinaryInput, idempotencyKey: string, options: RequestOptions = {}): Promise<DTO.Attachment> {
    const context = this.contextVersion;
    const selectedProject = reference(project), key = requestKey(idempotencyKey), signal = options.signal;
    const captured = validateClientModel("Attachment", parseClientJson(sealJson("Attachment", reservation)));
    projectIdentity(captured, selectedProject);
    let bytes: Uint8Array;
    if (content instanceof Uint8Array) {
      if (content.byteLength > this.maximumFile || content.byteLength !== captured.bytes) throw new ClientContractError("attachment_size");
      bytes = new Uint8Array(content);
    }
    else if (typeof Blob !== "undefined" && content instanceof Blob) {
      const blob = content.slice(); if (blob.size > this.maximumFile || blob.size !== captured.bytes) throw new ClientContractError("attachment_size");
      bytes = new Uint8Array(await blob.arrayBuffer());
      this.checkContext(context);
    } else throw new TypeError("Upload an explicit immutable Blob or owned byte array");
    if (bytes.byteLength > this.maximumFile || bytes.byteLength !== captured.bytes) throw new ClientContractError("attachment_size");
    const digest = await sha256(bytes);
    this.checkContext(context);
    if (digest !== captured.sha256) throw new ClientContractError("attachment_digest");
    // Exactly one requested PUT. Reservation and finalization remain separate explicit calls.
    const uploaded = await this.scoped("Attachment", selectedProject, ["attachments", captured.attachment_id, "content"],
      { method: "PUT", body: bytes, key, contentType: "application/octet-stream", signal }, value => {
        if (value.attachment_id !== captured.attachment_id || value.bytes !== captured.bytes || value.sha256 !== captured.sha256 ||
            value.name !== captured.name || value.media_type !== captured.media_type) throw new ClientContractError("attachment_identity");
      });
    this.checkContext(context, "committed"); return uploaded;
  }
  finalizeAttachment(project: string, attachment: string, body: DTO.AttachmentFinalize, idempotencyKey: string, options: RequestOptions = {}) {
    const sealed = sealJson("AttachmentFinalize", body), selected = reference(attachment);
    const declaration = validateClientModel("AttachmentFinalize", parseClientJson(sealed));
    return this.scoped("Attachment", project, ["attachments", selected, "finalize"], { method: "POST", body: sealed, key: idempotencyKey, contentType: "application/json", signal: options.signal }, value => {
      if (value.attachment_id !== selected || value.state !== "ready" || value.bytes !== declaration.bytes || value.sha256 !== declaration.sha256) throw new ClientContractError("attachment_identity");
    });
  }
  async downloadAttachment(project: string, metadata: DTO.Attachment, options: RequestOptions & { maxBytes?: number } = {}): Promise<DownloadedAttachment> {
    const context = this.contextVersion;
    const selectedProject = reference(project), signal = options.signal;
    const captured = validateClientModel("Attachment", parseClientJson(sealJson("Attachment", metadata)));
    projectIdentity(captured, selectedProject);
    const maximum = bounded(options.maxBytes ?? this.maximumFile, 256 * 1024 * 1024);
    if (captured.bytes > maximum) throw new ClientContractError("attachment_size");
    const bytes = await this.guarded(this.http.bytes({ segments: ["projects", selectedProject, "attachments", captured.attachment_id, "content"], signal }, maximum, async (data, response) => {
      if (data.byteLength !== captured.bytes || response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !== captured.media_type ||
          response.headers.get("etag") !== '"' + captured.sha256 + '"' || await sha256(data) !== captured.sha256) throw new ClientContractError("attachment_integrity");
      return data;
    }), context);
    this.checkContext(context);
    return { attachment: captured, bytes };
  }
  async *events(project: string, after: string, options: RequestOptions & StreamLimits & { authRevision?: string; kinds?: readonly DTO.Event["kind"][] } = {}): AsyncGenerator<DTO.Event> {
    const context = this.contextVersion;
    const selected = reference(project), cursor = reference(after, 2048), controller = new AbortController(), signal = options.signal;
    const authRevision = options.authRevision ?? this.snapshotAuth.get(selected);
    if (!authRevision) throw new SnapshotRequiredError("snapshot_required");
    const abort = () => controller.abort(); signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    const url = resourceUrl(this.http.endpoint, ["projects", selected, "events"]);
    if (options.kinds) { for (const kind of options.kinds) url.searchParams.append("kinds", kind); }
    const stream = new CommunicationEventStream({ projectId: selected, url, afterCursor: cursor, authRevision,
      maxEvents: options.maxEvents, maxBufferBytes: options.maxBufferBytes,
      getBearer: () => this.http.bearer(), fetch: this.fetcher });
    this.streams.add(controller);
    try {
      for await (const value of stream.events({ signal: controller.signal })) { this.checkContext(context); yield value; }
    } catch (error) {
      if (context === this.contextVersion && error instanceof Error && "requiresSnapshot" in error && error.requiresSnapshot === true) this.resetContext();
      throw error;
    }
    finally { controller.abort(); signal?.removeEventListener("abort", abort); this.streams.delete(controller); }
  }
  asPort(): CommunicationClient {
    const client = this;
    return {
      async send(project, request, key) {
        const context = client.contextVersion;
        const result = await client.sendMessage(project, request, key);
        client.checkContext(context, "committed");
        return { messageHandle: result.message.message_handle, operationRef: result.operation_ref, duplicate: result.duplicate,
          nativeState: result.delivery.native.state, explicitReplyHandle: result.message.first_reply_handle };
      },
      async readMessage(project, handle, offset = 0) {
        const context = client.contextVersion, value = await client.readMessage(project, handle, { offset });
        client.checkContext(context); return jsonValue(value);
      },
      async snapshot(project) {
        const value = await client.snapshotView(project);
        if (client.snapshotAuth.get(project) !== value.auth_revision) throw new CommunicationHttpError("authorization_changed");
        return { snapshotId: value.snapshot_id, afterCursor: value.after_cursor, data: jsonValue(value) };
      },
      async *watch(project, after, signal) {
        const authRevision = client.snapshotAuth.get(project);
        if (!authRevision) throw new SnapshotRequiredError("snapshot_required");
        for await (const value of client.events(project, after, { signal, authRevision })) {
          const event: CommunicationEvent = { eventId: value.event_id, cursor: value.cursor, resourceRef: value.resource_ref,
            revision: value.resource_revision, kind: value.kind, payload: jsonValue(value.payload) };
          yield event;
        }
      },
      async markRead(project, conversation, throughHandle, revision, key) {
        const context = client.contextVersion;
        const value = await client.markRead(project, conversation, { through_message_handle: throughHandle }, { expectedRevision: revision, requestId: key });
        client.checkContext(context, "committed"); return jsonValue(value);
      },
    };
  }
}
