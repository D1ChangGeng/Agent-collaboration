import type { Event as AcsEvent } from "./client-contracts.ts";
import { validateCommunicationEvent } from "./communication-state.ts";
import { checkedBearer, checkedEndpoint } from "./communication-http.ts";

export class StreamReplayError extends Error {
  readonly code: string;
  readonly resumeCursor: string | null;
  readonly requiresSnapshot = false;
  constructor(code: string, resumeCursor: string | null) {
    super("ACS stream stopped; resume from the last emitted cursor");
    this.name = "StreamReplayError"; this.code = code; this.resumeCursor = resumeCursor;
  }
}
export class SnapshotRequiredError extends Error {
  readonly code: string = "snapshot_required";
  readonly reason: string;
  readonly status: number | null;
  readonly resumeCursor = null;
  readonly requiresSnapshot = true;
  constructor(reason = "cursor_expired", status: number | null = null) {
    super("A new authorized ACS snapshot is required");
    this.name = "SnapshotRequiredError"; this.reason = reason; this.status = status;
  }
}
export class StreamAuthenticationError extends SnapshotRequiredError {
  readonly code = "authentication_lost";
  constructor(status = 401) { super("authentication_lost", status); this.name = "StreamAuthenticationError"; }
}
export class CursorMismatchError extends Error {
  readonly code = "cursor_mismatch";
  constructor() { super("Last-Event-ID and after_cursor must identify the same ACS position"); this.name = "CursorMismatchError"; }
}

export type SseFrame = Readonly<{ id: string; event: string; data: string }>;
export type StreamLimits = { maxEvents?: number; maxBufferBytes?: number };
const encoder = new TextEncoder();
function cursor(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 2048 && !/[\r\n\0]/.test(value);
}
function limits(options: StreamLimits): { maxEvents: number; maxBufferBytes: number } {
  const maxEvents = options.maxEvents ?? 256;
  const maxBufferBytes = options.maxBufferBytes ?? 1048576;
  if (!Number.isSafeInteger(maxEvents) || maxEvents < 1 || maxEvents > 256 ||
      !Number.isSafeInteger(maxBufferBytes) || maxBufferBytes < 1 || maxBufferBytes > 1048576) {
    throw new TypeError("Invalid ACS stream buffer limits");
  }
  return { maxEvents, maxBufferBytes };
}

/** Incremental SSE framing. Complete queued events and partial UTF-8 share one budget. */
export class AcsSseParser {
  private decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
  private text = "";
  private lines: string[] = [];
  private eventName = "";
  private lastId = "";
  private currentBytes = 0;
  private wireBytes = 0;
  private firstText = true;
  private skipLf = false;
  private finished = false;
  private failure: StreamReplayError | null = null;
  private emitted: string | null = null;
  private queue: Array<{ frame: SseFrame; bytes: number }> = [];
  private bounds: { maxEvents: number; maxBufferBytes: number };
  constructor(options: StreamLimits = {}) { this.bounds = limits(options); }
  get resumeCursor(): string | null { return this.emitted; }
  get bufferedEvents(): number { return this.queue.length; }
  get bufferedBytes(): number { return this.wireBytes + encoder.encode(this.lastId + this.eventName).byteLength; }

  private fail(code: string): never {
    const failure = new StreamReplayError(code, this.emitted);
    this.failure = failure; this.text = ""; this.lines = []; this.queue = []; this.wireBytes = 0;
    this.currentBytes = 0; this.eventName = ""; this.lastId = "";
    throw failure;
  }

  push(chunk: Uint8Array): void {
    if (this.failure) throw this.failure;
    if (this.finished) this.fail("parser_finished");
    if (!(chunk instanceof Uint8Array)) throw new TypeError("SSE chunks must be UTF-8 bytes");
    if (this.bufferedBytes + chunk.byteLength > this.bounds.maxBufferBytes) this.fail("buffer_overflow");
    this.wireBytes += chunk.byteLength;
    let decoded: string;
    try { decoded = this.decoder.decode(chunk, { stream: true }); }
    catch { this.fail("invalid_utf8"); }
    if (this.firstText && decoded.length > 0) {
      this.firstText = false;
      if (decoded[0] === "\ufeff") { decoded = decoded.slice(1); this.wireBytes -= 3; }
    }
    this.text += decoded;
    this.scan();
    if (this.bufferedBytes > this.bounds.maxBufferBytes) this.fail("buffer_overflow");
  }

  private scan(): void {
    if (this.skipLf && this.text.length > 0) {
      this.skipLf = false;
      if (this.text[0] === "\n") { this.text = this.text.slice(1); this.wireBytes -= 1; }
    }
    while (true) {
      const end = this.text.search(/[\r\n]/);
      if (end < 0) return;
      const line = this.text.slice(0, end);
      const cr = this.text[end] === "\r";
      const newline = cr && this.text[end + 1] === "\n" ? 2 : 1;
      this.skipLf = cr && end + 1 === this.text.length;
      this.text = this.text.slice(end + newline);
      const bytes = encoder.encode(line).byteLength + newline;
      if (line === "") {
        this.wireBytes -= bytes;
        if (this.lines.length > 0) {
          if (this.queue.length >= this.bounds.maxEvents) this.fail("slow_consumer");
          this.queue.push({ frame: { id: this.lastId, event: this.eventName || "message", data: this.lines.join("\n") }, bytes: this.currentBytes });
        } else {
          this.wireBytes -= this.currentBytes;
        }
        this.currentBytes = 0; this.lines = []; this.eventName = "";
        continue;
      }
      if (line.startsWith(":")) { this.wireBytes -= bytes; continue; }
      const colon = line.indexOf(":");
      const field = colon < 0 ? line : line.slice(0, colon);
      let value = colon < 0 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "data") {
        if (this.lines.length === 0 && this.queue.length >= this.bounds.maxEvents) this.fail("slow_consumer");
        this.lines.push(value);
      }
      else if (field === "event") {
        if (value.length > 512) this.fail("invalid_event_name");
        this.eventName = value;
      } else if (field === "id" && !value.includes("\0")) {
        if (value.length > 2048) this.fail("invalid_event_id");
        this.lastId = value;
      } else { this.wireBytes -= bytes; continue; }
      this.currentBytes += bytes;
    }
  }

  next(): SseFrame | null {
    if (this.failure) throw this.failure;
    const queued = this.queue.shift();
    if (!queued) return null;
    this.wireBytes -= queued.bytes;
    this.emitted = queued.frame.id || null;
    return queued.frame;
  }

  finish(): void {
    if (this.failure) throw this.failure;
    if (this.finished) return;
    try { this.text += this.decoder.decode(); }
    catch { this.fail("invalid_utf8"); }
    this.scan();
    if (this.lines.length === 0 && (this.text === "" || this.text.startsWith(":"))) {
      this.wireBytes -= this.currentBytes + encoder.encode(this.text).byteLength;
      this.currentBytes = 0; this.text = ""; this.eventName = "";
    }
    if (this.text.length > 0 || this.lines.length > 0 || this.currentBytes > 0) this.fail("incomplete_event");
    this.finished = true;
  }
}

export type CommunicationStreamOptions = StreamLimits & {
  projectId: string;
  url: string | URL;
  getBearer: () => string | Promise<string>;
  fetch?: typeof globalThis.fetch;
  afterCursor?: string;
  lastEventId?: string;
  authRevision?: string;
};

/** One explicit read-only connection. Reconnect and fresh snapshot decisions belong to the caller. */
export class CommunicationEventStream {
  private projectId: string;
  private url: URL;
  private getBearer: () => string | Promise<string>;
  private fetcher: typeof globalThis.fetch;
  private authRevision: string | undefined;
  private bounds: { maxEvents: number; maxBufferBytes: number };
  private emitted: string | null;
  private active = false;
  private snapshotNeeded = false;
  constructor(options: CommunicationStreamOptions) {
    this.projectId = options.projectId;
    this.url = checkedEndpoint(options.url);
    if (!this.projectId || [...this.projectId].length > 512 || typeof options.getBearer !== "function") {
      throw new TypeError("An explicit ACS endpoint and bearer callback are required");
    }
    const query = this.url.searchParams.getAll("after_cursor");
    if (query.length > 1) throw new CursorMismatchError();
    const positions = [options.afterCursor, options.lastEventId, ...query].filter(value => value !== undefined);
    if (positions.some(value => !cursor(value)) || new Set(positions).size > 1) throw new CursorMismatchError();
    this.emitted = positions[0] ?? null;
    this.url.searchParams.delete("after_cursor");
    this.getBearer = options.getBearer;
    this.fetcher = options.fetch ?? globalThis.fetch;
    this.authRevision = options.authRevision;
    this.bounds = limits(options);
  }
  get resumeCursor(): string | null { return this.emitted; }
  get requiresSnapshot(): boolean { return this.snapshotNeeded; }

  async *events(options: { signal?: AbortSignal } = {}): AsyncGenerator<AcsEvent> {
    if (this.snapshotNeeded) throw new SnapshotRequiredError("new_stream_from_snapshot_required");
    if (this.active) throw new StreamReplayError("stream_already_active", this.emitted);
    this.active = true;
    const controller = new AbortController();
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    const abort = () => {
      controller.abort();
      if (reader) void reader.cancel().catch(() => {});
    };
    options.signal?.addEventListener("abort", abort, { once: true });
    if (options.signal?.aborted) controller.abort();
    try {
      let bearer: string;
      try { bearer = checkedBearer(await this.getBearer()); }
      catch { throw new StreamAuthenticationError(); }
      const url = new URL(this.url);
      const headers = new Headers({ Accept: "text/event-stream", Authorization: "Bearer " + bearer });
      if (this.emitted !== null) {
        url.searchParams.set("after_cursor", this.emitted);
        try { headers.set("Last-Event-ID", this.emitted); }
        catch { throw new StreamReplayError("invalid_cursor", this.emitted); }
      }
      let response: Response;
      try { response = await this.fetcher(url, { method: "GET", headers, signal: controller.signal, redirect: "error", credentials: "omit" }); }
      catch { throw new StreamReplayError(controller.signal.aborted ? "aborted" : "network_error", this.emitted); }
      if (response.status === 401 || response.status === 403) throw new StreamAuthenticationError(response.status);
      if (response.status === 410) throw new SnapshotRequiredError("cursor_expired", 410);
      if (!response.ok) throw new StreamReplayError("http_" + response.status, this.emitted);
      if (response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !== "text/event-stream" || !response.body) {
        throw new StreamReplayError("invalid_content_type", this.emitted);
      }
      reader = response.body.getReader();
      const parser = new AcsSseParser(this.bounds);
      while (true) {
        if (controller.signal.aborted) throw new StreamReplayError("aborted", this.emitted);
        let chunk: ReadableStreamReadResult<Uint8Array>;
        try { chunk = await reader.read(); }
        catch { throw new StreamReplayError(controller.signal.aborted ? "aborted" : "network_error", this.emitted); }
        if (controller.signal.aborted) throw new StreamReplayError("aborted", this.emitted);
        try {
          if (chunk.done) parser.finish();
          else parser.push(chunk.value);
        } catch (error) {
          if (error instanceof StreamReplayError) throw new StreamReplayError(error.code, this.emitted);
          throw error;
        }
        let frame: SseFrame | null;
        while ((frame = parser.next()) !== null) {
          let event: AcsEvent;
          try { event = validateCommunicationEvent(JSON.parse(frame.data)); }
          catch { throw new StreamReplayError("invalid_event", this.emitted); }
          if (event.project_id !== this.projectId || frame.id !== event.cursor ||
              frame.event !== "message" && frame.event !== event.kind) throw new StreamReplayError("event_identity_mismatch", this.emitted);
          if (this.authRevision !== undefined && event.auth_revision !== this.authRevision && event.kind !== "permission.changed") {
            throw new SnapshotRequiredError("authorization_changed");
          }
          const reset = event.kind === "permission.changed" || event.kind === "resync.required" || event.payload.reset_required === true;
          if (reset) {
            this.emitted = null; this.snapshotNeeded = true;
            if (event.resource_ref !== null || ["message_handle", "conversation_id", "operation_ref"].some(key => key in event.payload)) {
              throw new SnapshotRequiredError("unsafe_control_envelope");
            }
            yield event;
            throw new SnapshotRequiredError(event.payload.reason_code ?? event.kind);
          }
          this.emitted = event.cursor;
          yield event;
        }
        if (chunk.done) return;
      }
    } catch (error) {
      if (error instanceof SnapshotRequiredError) { this.emitted = null; this.snapshotNeeded = true; }
      throw error;
    } finally {
      controller.abort();
      options.signal?.removeEventListener("abort", abort);
      if (reader) {
        try { await reader.cancel(); } catch { /* A failed connection is already closed. */ }
        reader.releaseLock();
      }
      this.active = false;
    }
  }
}
