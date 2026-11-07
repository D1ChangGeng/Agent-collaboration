import { clientModelSchemas } from "./client-runtime-schema.ts";
import type { ClientModelName, ClientModels } from "./client-runtime-schema.ts";

export type JsonSchema = boolean | Readonly<{
  $ref?: string; type?: string | readonly string[]; properties?: Readonly<Record<string, JsonSchema>>;
  required?: readonly string[]; additionalProperties?: JsonSchema; items?: JsonSchema;
  minProperties?: number; default?: unknown;
  minItems?: number; maxItems?: number; uniqueItems?: boolean; minLength?: number; maxLength?: number;
  minimum?: number; maximum?: number; pattern?: string; format?: string; const?: unknown; enum?: readonly unknown[];
  allOf?: readonly JsonSchema[]; anyOf?: readonly JsonSchema[]; oneOf?: readonly JsonSchema[];
  if?: JsonSchema; then?: JsonSchema; else?: JsonSchema; title?: string; description?: string;
}>;
export class ClientContractError extends Error {
  readonly code = "invalid_contract";
  readonly model: string;
  constructor(model: string) { super("ACS data failed its admitted client contract"); this.name = "ClientContractError"; this.model = model; }
}
export const JSON_LIMITS = Object.freeze({ maxBytes: 32 * 1024 * 1024, maxNodes: 100000, maxDepth: 64 });
const encoder = new TextEncoder();
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
function validString(value: string): boolean {
  for (const char of value) { const code = char.codePointAt(0)!; if (code >= 0xd800 && code <= 0xdfff) return false; }
  return true;
}
function jsonBounds(value: unknown): void {
  let nodes = 0;
  const ancestors = new Set<object>();
  function visit(item: unknown, depth: number): void {
    if (++nodes > JSON_LIMITS.maxNodes || depth > JSON_LIMITS.maxDepth) throw new ClientContractError("JSON");
    if (typeof item === "string") { if (item.length > JSON_LIMITS.maxBytes || !validString(item)) throw new ClientContractError("JSON"); }
    else if (typeof item === "number") {
      if (!Number.isFinite(item) || Number.isInteger(item) && !Number.isSafeInteger(item)) throw new ClientContractError("JSON");
    } else if (item !== null && typeof item === "object") {
      if (ancestors.has(item) || !Array.isArray(item) && ![null, Object.prototype].includes(Object.getPrototypeOf(item))) throw new ClientContractError("JSON");
      const descriptors = Object.getOwnPropertyDescriptors(item);
      if (Reflect.ownKeys(item).some(key => typeof key !== "string" || key !== "length" && !descriptors[key].enumerable ||
          descriptors[key].get !== undefined || descriptors[key].set !== undefined)) throw new ClientContractError("JSON");
      ancestors.add(item);
      if (Array.isArray(item)) { for (const child of item) visit(child, depth + 1); }
      else { for (const [key, child] of Object.entries(item)) { if (!validString(key)) throw new ClientContractError("JSON"); visit(child, depth + 1); } }
      ancestors.delete(item);
    } else if (item !== null && typeof item !== "boolean") throw new ClientContractError("JSON");
  }
  visit(value, 0);
  if (encoder.encode(JSON.stringify(value)).byteLength > JSON_LIMITS.maxBytes) throw new ClientContractError("JSON");
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (object(value)) return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
  return JSON.stringify(value);
}
export function awareTimestamp(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:[Zz]|[+-](\d{2}):(\d{2}))$/.exec(value);
  if (!match) return false;
  const [year, month, day, hour, minute, second, offsetHour, offsetMinute] = match.slice(1).map(value => value === undefined ? 0 : Number(value));
  const days = [31, year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year >= 1 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1] && hour < 24 && minute < 60 && second < 60 && offsetHour < 24 && offsetMinute < 60;
}
function matches(schema: JsonSchema, value: unknown, state: { steps: number }, refs = new Set<string>()): boolean {
  if (++state.steps > 2000000) throw new ClientContractError("complexity");
  if (typeof schema === "boolean") return schema;
  if (schema.$ref !== undefined) {
    if (!schema.$ref.startsWith("#/$defs/") || refs.has(schema.$ref)) throw new ClientContractError("schema_source");
    const target = clientModelSchemas[schema.$ref.slice(8)];
    if (target === undefined) throw new ClientContractError("schema_source");
    if (!matches(target, value, state, new Set([...refs, schema.$ref]))) return false;
  }
  if (schema.type !== undefined) {
    const types = typeof schema.type === "string" ? [schema.type] : schema.type;
    if (!types.some(type => type === "null" ? value === null : type === "array" ? Array.isArray(value) :
      type === "object" ? object(value) : type === "integer" ? Number.isSafeInteger(value) : typeof value === type)) return false;
  }
  if ("const" in schema && canonical(value) !== canonical(schema.const)) return false;
  if (schema.enum && !schema.enum.some(item => canonical(item) === canonical(value))) return false;
  if (schema.allOf && !schema.allOf.every(child => matches(child, value, state, refs))) return false;
  if (schema.anyOf && !schema.anyOf.some(child => matches(child, value, state, refs))) return false;
  if (schema.oneOf && schema.oneOf.filter(child => matches(child, value, state, refs)).length !== 1) return false;
  if (schema.if !== undefined) {
    const branch = matches(schema.if, value, state, refs) ? schema.then : schema.else;
    if (branch !== undefined && !matches(branch, value, state, refs)) return false;
  }
  if (typeof value === "string") {
    const length = [...value].length;
    if (schema.minLength !== undefined && length < schema.minLength || schema.maxLength !== undefined && length > schema.maxLength ||
        schema.pattern !== undefined && !new RegExp(schema.pattern, "u").test(value) || schema.format === "date-time" && !awareTimestamp(value)) return false;
  }
  if (typeof value === "number" && (schema.minimum !== undefined && value < schema.minimum || schema.maximum !== undefined && value > schema.maximum)) return false;
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems || schema.maxItems !== undefined && value.length > schema.maxItems ||
        schema.uniqueItems && new Set(value.map(canonical)).size !== value.length) return false;
    if (schema.items !== undefined && !value.every(item => matches(schema.items!, item, state, refs))) return false;
  }
  if (object(value)) {
    if (schema.minProperties !== undefined && Object.keys(value).length < schema.minProperties) return false;
    if (schema.required?.some(key => !Object.hasOwn(value, key))) return false;
    for (const [key, child] of Object.entries(value)) {
      const declared = schema.properties && Object.hasOwn(schema.properties, key) ? schema.properties[key] : undefined;
      if (declared !== undefined) { if (!matches(declared, child, state, refs)) return false; }
      else if (schema.additionalProperties !== undefined && !matches(schema.additionalProperties, child, state, refs)) return false;
    }
  }
  return true;
}
export function assertClientModel<N extends ClientModelName>(name: N, value: unknown): asserts value is ClientModels[N] {
  jsonBounds(value);
  if (!Object.hasOwn(clientModelSchemas, name) || !matches(clientModelSchemas[name], value, { steps: 0 })) throw new ClientContractError(name);
}
export function validateClientModel<N extends ClientModelName>(name: N, value: unknown): ClientModels[N] {
  assertClientModel(name, value); return value;
}
/** Strict JSON grammar, duplicate-key rejection and finite/safe numbers, with bounded allocation. */
export function parseClientJson(text: string): unknown {
  if (text.length > JSON_LIMITS.maxBytes || encoder.encode(text).byteLength > JSON_LIMITS.maxBytes) throw new ClientContractError("JSON");
  let position = 0, nodes = 0;
  const fail = (): never => { throw new ClientContractError("JSON"); };
  const whitespace = () => { while (/[ \t\r\n]/.test(text[position] ?? "x")) position++; };
  function string(): string {
    const start = position++;
    let escaped = false;
    while (position < text.length) {
      const char = text[position++];
      if (!escaped && char === '"') {
        let result: unknown;
        try { result = JSON.parse(text.slice(start, position)); } catch { return fail(); }
        if (typeof result !== "string" || !validString(result)) return fail();
        return result;
      }
      if (escaped) escaped = false; else if (char === "\\") escaped = true;
    }
    return fail();
  }
  function value(depth: number): unknown {
    whitespace();
    if (++nodes > JSON_LIMITS.maxNodes || depth > JSON_LIMITS.maxDepth) return fail();
    const char = text[position];
    if (char === '"') return string();
    if (char === "{") {
      position++; whitespace();
      const result: Record<string, unknown> = {}, keys = new Set<string>();
      if (text[position] === "}") { position++; return result; }
      while (true) {
        if (text[position] !== '"') return fail();
        const key = string(); if (keys.has(key)) return fail(); keys.add(key);
        whitespace(); if (text[position++] !== ":") return fail();
        Object.defineProperty(result, key, { value: value(depth + 1), enumerable: true, writable: true, configurable: true });
        whitespace(); const separator = text[position++];
        if (separator === "}") return result;
        if (separator !== ",") return fail();
        whitespace();
      }
    }
    if (char === "[") {
      position++; whitespace(); const result: unknown[] = [];
      if (text[position] === "]") { position++; return result; }
      while (true) {
        result.push(value(depth + 1)); whitespace(); const separator = text[position++];
        if (separator === "]") return result;
        if (separator !== ",") return fail();
      }
    }
    for (const [token, literal] of [["true", true], ["false", false], ["null", null]] as const) {
      if (text.startsWith(token, position)) { position += token.length; return literal; }
    }
    const match = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(text.slice(position));
    if (!match) return fail();
    position += match[0].length; const number = Number(match[0]);
    if (!Number.isFinite(number) || Number.isInteger(number) && !Number.isSafeInteger(number)) return fail();
    return number;
  }
  const result = value(0); whitespace(); if (position !== text.length) return fail(); return result;
}
