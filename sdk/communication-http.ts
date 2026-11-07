import { ClientContractError, parseClientJson, validateClientModel } from "./client-validation.ts";
import type { ClientModelName, ClientModels } from "./client-runtime-schema.ts";
import type { Problem } from "./client-contracts.ts";

export type EffectState = "none" | "committed" | "native_possible" | "unknown";
export class CommunicationHttpError extends Error {
  readonly code: string;
  readonly status: number | null;
  readonly effectState: EffectState;
  readonly retryable: boolean;
  readonly operationRef: string | null;
  readonly requestId: string | null;
  readonly requiresSnapshot: boolean;
  constructor(code: string, options: { status?: number | null; effectState?: EffectState; retryable?: boolean; operationRef?: string | null; requestId?: string | null } = {}) {
    super("ACS HTTP operation did not produce a validated result"); this.name = "CommunicationHttpError";
    this.code = code; this.status = options.status ?? null; this.effectState = options.effectState ?? "none";
    this.retryable = options.retryable ?? false; this.operationRef = options.operationRef ?? null; this.requestId = options.requestId ?? null;
    this.requiresSnapshot = this.status === 401 || this.status === 403 || ["authentication_lost", "authorization_changed", "permission_changed"].includes(code);
  }
}
/** The Stream's existing endpoint admission, shared with REST after integration. */
export function checkedEndpoint(value: string | URL): URL {
  const url = new URL(value);
  if (url.username || url.password || url.hash || !["https:", "http:"].includes(url.protocol) ||
      ["access_token", "token", "authorization", "bearer"].some(key => url.searchParams.has(key))) {
    throw new TypeError("An explicit ACS endpoint and bearer callback are required");
  }
  return url;
}
/** Exact existing Stream bearer grammar. No tokens enter URLs, errors or logs. */
export function checkedBearer(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9._~+/-]+=*$/.test(value) || value.length > 8192) {
    throw new CommunicationHttpError("authentication_lost", { status: 401 });
  }
  return value;
}
export function reference(value: unknown, maximum = 512): string {
  if (typeof value !== "string" || !value.length || [...value].length > maximum || /[\u0000-\u001f\u007f]/.test(value)) {
    throw new TypeError("A bounded explicit ACS reference is required");
  }
  return value;
}
export function requestKey(value: unknown): string {
  return reference(value, 200);
}
export function ifMatch(value: string | number): string {
  const text = typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? String(value) : value;
  if (typeof text !== "string" || !/^(0|[1-9][0-9]{0,18})$/.test(text) || BigInt(text) > 9223372036854775806n) {
    throw new TypeError("A canonical bounded ACS revision is required");
  }
  return '"' + text + '"';
}
export function resourceUrl(endpoint: URL, segments: readonly string[], query: Readonly<Record<string, string | number | boolean | null | undefined>> = {}): URL {
  const base = checkedEndpoint(endpoint);
  if (base.search) throw new TypeError("ACS base endpoint cannot contain a query");
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  const url = new URL(segments.map(value => {
    const selected = reference(value);
    if (selected === "." || selected === "..") throw new TypeError("ACS references cannot be URL dot segments");
    return encodeURIComponent(selected);
  }).join("/"), base);
  for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== null) {
    if (typeof value === "number" && !Number.isSafeInteger(value) || [...String(value)].length > 8192) throw new TypeError("Invalid ACS query bound");
    url.searchParams.set(key, String(value));
  }
  return url;
}
export async function readBoundedBytes(response: Response, maximum: number, signal?: AbortSignal): Promise<Uint8Array> {
  if (!Number.isSafeInteger(maximum) || maximum < 1 || maximum > 256 * 1024 * 1024) throw new TypeError("Invalid ACS response byte bound");
  const length = response.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || !Number.isSafeInteger(Number(length)) || Number(length) > maximum)) throw new ClientContractError("response_size");
  if (!response.body) { if (length !== null && Number(length) !== 0) throw new ClientContractError("response_size"); return new Uint8Array(); }
  const reader = response.body.getReader(), chunks: Uint8Array[] = [];
  let total = 0;
  const abort = () => { void reader.cancel().catch(() => {}); };
  signal?.addEventListener("abort", abort, { once: true });
  try {
    while (true) {
      if (signal?.aborted) throw new CommunicationHttpError("aborted");
      const item = await reader.read();
      if (signal?.aborted) throw new CommunicationHttpError("aborted");
      if (item.done) break;
      total += item.value.byteLength;
      if (total > maximum) throw new ClientContractError("response_size");
      chunks.push(new Uint8Array(item.value));
    }
    if (length !== null && total !== Number(length)) throw new ClientContractError("response_size");
    const result = new Uint8Array(total); let offset = 0;
    for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength; }
    return result;
  } finally {
    signal?.removeEventListener("abort", abort);
    try { await reader.cancel(); } catch { /* Failed I/O is reported by the owning operation. */ }
    reader.releaseLock();
  }
}
export function sealJson<N extends ClientModelName>(name: N, value: unknown): string {
  const encoded = JSON.stringify(validateClientModel(name, value));
  validateClientModel(name, parseClientJson(encoded));
  return encoded;
}
export type HttpOptions = {
  endpoint: string | URL; getBearer: () => string | Promise<string>; fetch?: typeof globalThis.fetch;
  maxResponseBytes?: number;
};
export type HttpRequest = {
  method?: "GET" | "POST" | "PUT" | "DELETE"; segments: readonly string[];
  query?: Readonly<Record<string, string | number | boolean | null | undefined>>;
  body?: string | Uint8Array; key?: string; revision?: string | number; contentType?: string;
  mutating?: boolean; signal?: AbortSignal;
};
/** Stateless one-request transport. It never retries a write or executes pending work. */
export class CommunicationHttpTransport {
  private base: URL;
  readonly maximum: number;
  private getBearer: () => string | Promise<string>;
  private fetcher: typeof globalThis.fetch;
  private closed = false;
  private controllers = new Set<AbortController>();
  constructor(options: HttpOptions) {
    this.base = checkedEndpoint(options.endpoint);
    if (this.base.search || typeof options.getBearer !== "function") throw new TypeError("An explicit ACS base and bearer callback are required");
    this.maximum = options.maxResponseBytes ?? 32 * 1024 * 1024;
    if (!Number.isSafeInteger(this.maximum) || this.maximum < 1 || this.maximum > 32 * 1024 * 1024) throw new TypeError("Invalid ACS JSON response bound");
    this.getBearer = options.getBearer; this.fetcher = options.fetch ?? globalThis.fetch;
  }
  get endpoint(): URL { return new URL(this.base); }
  advanceContext(): void { for (const controller of this.controllers) controller.abort(); }
  close(): void { this.closed = true; for (const controller of this.controllers) controller.abort(); }
  async bearer(): Promise<string> {
    if (this.closed) throw new CommunicationHttpError("authorization_changed");
    try { return checkedBearer(await this.getBearer()); }
    catch (error) { if (error instanceof CommunicationHttpError) throw error; throw new CommunicationHttpError("authentication_lost", { status: 401 }); }
  }
  private async response<T>(input: HttpRequest, consume: (response: Response, signal: AbortSignal) => Promise<T>): Promise<T> {
    // Capture all mutable caller input before awaiting credential acquisition.
    const method = input.method ?? "GET", mutating = input.mutating ?? (method !== "GET"), signal = input.signal;
    const url = resourceUrl(this.endpoint, [...input.segments], { ...input.query });
    if (input.body instanceof Uint8Array && input.body.byteLength > 256 * 1024 * 1024 ||
        typeof input.body === "string" && input.body.length > 32 * 1024 * 1024) throw new ClientContractError("request_size");
    const body = input.body instanceof Uint8Array ? new Uint8Array(input.body) : input.body;
    const headers = new Headers({ Accept: "application/json" });
    if (input.key !== undefined) headers.set("Idempotency-Key", requestKey(input.key));
    if (input.revision !== undefined) headers.set("If-Match", ifMatch(input.revision));
    if (input.contentType) headers.set("Content-Type", input.contentType);
    const controller = new AbortController(), abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    this.controllers.add(controller);
    let attempted = false, validatedProblem = false;
    try {
      const bearer = await this.bearer();
      if (controller.signal.aborted || this.closed) throw new CommunicationHttpError("aborted");
      headers.set("Authorization", "Bearer " + bearer);
      attempted = true;
      const response = await this.fetcher(url, { method, headers, body, signal: controller.signal, redirect: "error", credentials: "omit" });
      if (controller.signal.aborted || this.closed) throw new CommunicationHttpError("authorization_changed");
      if (!response.ok) {
        let problem: Problem;
        try {
          const type = response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase();
          if (type !== "application/problem+json" && type !== "application/json") throw new ClientContractError("Problem");
          const bytes = await readBoundedBytes(response, Math.min(this.maximum, 65536), controller.signal);
          const value = parseClientJson(new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes));
          problem = validateClientModel("Problem", value);
        } catch { throw new CommunicationHttpError("invalid_error_response", { status: response.status, effectState: mutating ? "unknown" : "none" }); }
        validatedProblem = true;
        throw new CommunicationHttpError(problem.error.code, { status: response.status, effectState: problem.error.effect_state,
          retryable: problem.error.retryable, operationRef: problem.error.operation_ref, requestId: problem.request_id });
      }
      const value = await consume(response, controller.signal);
      if (controller.signal.aborted || this.closed) throw new CommunicationHttpError("authorization_changed");
      return value;
    } catch (error) {
      if (error instanceof CommunicationHttpError) {
        if (mutating && attempted && !validatedProblem && error.effectState === "none") {
          throw new CommunicationHttpError(error.code, { status: error.status, effectState: "unknown", operationRef: error.operationRef, requestId: error.requestId });
        }
        throw error;
      }
      throw new CommunicationHttpError(attempted ? error instanceof ClientContractError ? "invalid_response" : "network_error" : "request_unavailable",
        { effectState: mutating && attempted ? "unknown" : "none" });
    } finally { controller.abort(); signal?.removeEventListener("abort", abort); this.controllers.delete(controller); }
  }
  json<N extends ClientModelName>(name: N, input: HttpRequest, verify?: (value: ClientModels[N]) => void): Promise<ClientModels[N]> {
    return this.response(input, async (response, signal) => {
      if (response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !== "application/json") throw new ClientContractError(name);
      const bytes = await readBoundedBytes(response, this.maximum, signal);
      let value: unknown;
      try { value = parseClientJson(new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes)); }
      catch { throw new ClientContractError(name); }
      const validated = validateClientModel(name, value); verify?.(validated); return validated;
    });
  }
  bytes(input: HttpRequest, maximum: number, consume: (bytes: Uint8Array, response: Response) => Promise<Uint8Array>): Promise<Uint8Array> {
    return this.response(input, async (response, signal) => consume(await readBoundedBytes(response, maximum, signal), response));
  }
}
