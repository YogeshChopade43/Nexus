/**
 * Human-friendly names, summaries and form fields for MCP tools, from whatever the server provides.
 * Generic on purpose: no per-app tables, just cleanup of common shapes (e.g. Notion's
 * "API-post-search" + "Notion | Search by title\nError Responses: ...").
 */

export interface ToolLike {
  remote_name?: string;
  name?: string;
  description?: string;
  title?: string | null;
  read_only?: boolean | null;
  destructive?: boolean | null;
  policy?: string;
}

const MAX_LABEL = 60;

/** Description without an "App | " prefix, error-code tables or markdown noise. */
export function cleanDescription(description = ''): string {
  let text = description.replace(/^\[[^\]]+\]\s*/, ''); // Nexus adds "[Server] "
  const pipe = text.indexOf(' | ');
  if (pipe > 0 && pipe <= 30 && !text.slice(0, pipe).includes('\n')) text = text.slice(pipe + 3);
  text = text.split(/\n\s*(Error Responses|Errors|Returns|Raises|Example[s]?)\s*:/i)[0];
  return text.replace(/\*\*|`/g, '').replace(/\s+/g, ' ').trim();
}

/** "API-get-block-children" -> "Get block children"; "listPullRequests" -> "List pull requests". */
export function humanize(name: string): string {
  const words = name
    .replace(/^(api|tool|mcp)[-_.]/i, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .split(/[-_.\s]+/)
    .filter(Boolean)
    .map(w => (/^(id|ids|url|api|uuid|json|html)$/i.test(w) ? w.toUpperCase() : w.toLowerCase()));
  const text = words.join(' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function firstSentence(description: string): string {
  return description.split(/(?<=\.)\s|\n/)[0].replace(/\.$/, '').trim();
}

/** The name to show: a short description line beats the server's title, which beats the raw name. */
export function toolLabel(tool: ToolLike): string {
  const first = firstSentence(cleanDescription(tool.description));
  if (first && first.length <= MAX_LABEL) return first.charAt(0).toUpperCase() + first.slice(1);
  if (tool.title) return tool.title;
  return humanize(tool.remote_name ?? tool.name ?? '');
}

/** One or two lines of extra detail, or '' when the description is just the label. */
export function toolSummary(tool: ToolLike): string {
  const text = cleanDescription(tool.description);
  const label = toolLabel(tool);
  const rest = text.toLowerCase().startsWith(label.toLowerCase()) ? text.slice(label.length).replace(/^[.:\s-]+/, '') : text;
  return rest.length > 180 ? `${rest.slice(0, 177)}…` : rest;
}

const READ_VERBS = /^(search|query|list|get|retrieve|find|fetch|read|look up|show|count|check)\b/i;

/**
 * 'read' or 'write'. A label starting with a read verb wins (servers that wrap HTTP APIs often mark
 * every POST, like "Search by title", as destructive); then the server's hints, then Nexus's policy.
 */
export function toolKind(tool: ToolLike): 'read' | 'write' {
  if (READ_VERBS.test(toolLabel(tool)) || tool.read_only) return 'read';
  if (tool.destructive) return 'write';
  return tool.policy === 'ask' ? 'write' : 'read';
}

// ---- parameters -------------------------------------------------------------------------------

type Schema = {
  type?: string | string[];
  description?: string;
  enum?: unknown[];
  const?: unknown;
  default?: unknown;
  format?: string;
  deprecated?: boolean;
  properties?: Record<string, Schema>;
  required?: string[];
  items?: Schema;
  anyOf?: Schema[];
  oneOf?: Schema[];
  $ref?: string;
  $defs?: Record<string, Schema>;
  definitions?: Record<string, Schema>;
};

export interface ParamField {
  key: string;
  label: string;
  required: boolean;
  /** string | integer | number | boolean | object | array */
  type: string;
  options?: string[];
  description: string;
  defaultValue?: unknown;
  /** A JSON outline for object/array fields, built from the schema. */
  example?: string;
  deprecated: boolean;
}

function resolve(schema: Schema | undefined, root: Schema, depth = 0): Schema {
  if (!schema || depth > 5) return {};
  if (schema.$ref) {
    const name = schema.$ref.split('/').pop() ?? '';
    return resolve((root.$defs ?? root.definitions ?? {})[name], root, depth + 1);
  }
  // anyOf/oneOf: show the first structured option (servers often add a plain-string fallback).
  const options = schema.anyOf ?? schema.oneOf;
  if (options?.length) {
    const resolved = options.map(o => resolve(o, root, depth + 1));
    const picked = resolved.find(o => typeOf(o) === 'object' || typeOf(o) === 'array') ?? resolved[0];
    return { ...picked, description: schema.description ?? picked.description };
  }
  return schema;
}

function typeOf(schema: Schema): string {
  const type = Array.isArray(schema.type) ? schema.type.find(t => t !== 'null') : schema.type;
  if (type) return type;
  if (schema.properties) return 'object';
  if (schema.enum) return 'string';
  return 'string';
}

function outline(schema: Schema, root: Schema, depth = 0): unknown {
  const s = resolve(schema, root);
  const type = typeOf(s);
  if (s.const !== undefined) return s.const;
  if (s.enum?.length) return s.enum[0];
  if (type === 'object') {
    if (depth >= 2 || !s.properties) return {};
    const keys = s.required?.length ? s.required : Object.keys(s.properties).slice(0, 3);
    return Object.fromEntries(keys.map(k => [k, outline(s.properties![k] ?? {}, root, depth + 1)]));
  }
  if (type === 'array') return depth >= 2 ? [] : [outline(s.items ?? {}, root, depth + 1)];
  if (type === 'boolean') return false;
  if (type === 'integer' || type === 'number') return 0;
  return s.format === 'uuid' ? '<id>' : '…';
}

export function paramLabel(key: string): string {
  return humanize(key);
}

/** Form fields for a tool's input schema: required first, each with a type, choices and help text. */
export function paramFields(schema: Schema | undefined): ParamField[] {
  if (!schema?.properties) return [];
  const required = new Set(schema.required ?? []);
  const fields = Object.entries(schema.properties).map(([key, raw]): ParamField => {
    const s = resolve(raw, schema);
    const type = typeOf(s);
    const options = s.enum?.map(String);
    const description = cleanDescription(s.description ?? raw.description ?? '');
    return {
      key,
      label: paramLabel(key),
      required: required.has(key),
      type,
      options: options && options.length > 1 ? options : undefined,
      description,
      deprecated: !!(raw.deprecated || s.deprecated) || /^deprecated\b/i.test(description),
      defaultValue: s.default,
      example: type === 'object' || type === 'array' ? JSON.stringify(outline(s, schema), null, 2) : undefined,
    };
  });
  const optional = fields.filter(f => !f.required);
  return [...fields.filter(f => f.required), ...optional.filter(f => !f.deprecated), ...optional.filter(f => f.deprecated)];
}
