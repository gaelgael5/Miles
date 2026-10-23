import type { JsonSchema } from "jsonjoy-builder";
import { YAMLParseError, parse, stringify } from "yaml";

/** Le schéma lu dans le YAML, ou pourquoi il ne se lit pas (ligne et colonne). */
export type Parsed = { ok: true; schema: JsonSchema } | { ok: false; message: string };

// Même forme que le serveur (story 0f7cda10) : un modèle se désigne par un URI absolu.
const ID_RE = /^miles:\/(?:shared\/([a-z0-9][a-z0-9_-]*)|domains\/([a-z0-9][a-z0-9_-]*)\/([a-z0-9][a-z0-9_-]*))$/;

export function modelUri(scope: string, name: string): string {
  return scope === "shared" ? `miles:/shared/${name}` : `miles:/domains/${scope}/${name}`;
}

export function targetOf(uri: string): [string, string] | null {
  const match = ID_RE.exec(uri.split("#")[0] ?? "");
  if (match === null) return null;
  return match[1] !== undefined ? ["shared", match[1]] : [match[2] ?? "", match[3] ?? ""];
}

// Mots-clés dont la valeur est un schéma, une liste ou une table de schémas : c'est là
// qu'un YAML en cours de frappe (`age:` sans rien dessous) laisse un `null`, sur lequel
// l'éditeur visuel plante au lieu de l'ignorer.
const ONE = ["items", "additionalProperties", "not", "if", "then", "else", "contains", "propertyNames"];
const MANY = ["allOf", "anyOf", "oneOf", "prefixItems"];
const TABLE = ["properties", "patternProperties", "$defs", "definitions", "dependentSchemas"];

function isSchema(value: unknown): boolean {
  return typeof value === "boolean" || (typeof value === "object" && value !== null && !Array.isArray(value));
}

/** Le premier sous-schéma qui n'en est pas un (ni objet ni booléen), ou null. */
export function incompleteAt(schema: unknown, path = ""): string | null {
  if (typeof schema !== "object" || schema === null) return null;
  const node = schema as Record<string, unknown>;
  for (const key of ONE) {
    if (key in node) {
      if (!isSchema(node[key])) return `${path}${key}`;
      const inner = incompleteAt(node[key], `${path}${key}.`);
      if (inner) return inner;
    }
  }
  for (const key of MANY) {
    const list = node[key];
    if (list === undefined) continue;
    if (!Array.isArray(list)) return `${path}${key}`;
    for (const [index, item] of list.entries()) {
      if (!isSchema(item)) return `${path}${key}.${index}`;
      const inner = incompleteAt(item, `${path}${key}.${index}.`);
      if (inner) return inner;
    }
  }
  for (const key of TABLE) {
    const table = node[key];
    if (table === undefined) continue;
    if (typeof table !== "object" || table === null || Array.isArray(table)) return `${path}${key}`;
    for (const [name, item] of Object.entries(table)) {
      if (!isSchema(item)) return `${path}${key}.${name}`;
      const inner = incompleteAt(item, `${path}${key}.${name}.`);
      if (inner) return inner;
    }
  }
  return null;
}

export function parseSchema(text: string): Parsed {
  try {
    const value: unknown = parse(text, { uniqueKeys: true });
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      return { ok: false, message: "le document n'est pas un objet" };
    }
    const incomplete = incompleteAt(value);
    if (incomplete !== null) {
      return { ok: false, message: `« ${incomplete} » n'est pas encore un schéma` };
    }
    return { ok: true, schema: value as JsonSchema };
  } catch (error) {
    if (error instanceof YAMLParseError) {
      const at = error.linePos?.[0];
      const where = at ? ` (ligne ${at.line}, colonne ${at.col})` : "";
      return { ok: false, message: `${error.message.split("\n")[0] ?? ""}${where}` };
    }
    throw error;
  }
}

export function schemaText(schema: JsonSchema): string {
  return stringify(schema, { lineWidth: 0 });
}

/**
 * Deux textes décrivent-ils le même schéma ? Le YAML régénéré par l'éditeur visuel ne
 * se présente pas comme celui du serveur : on compare ce qu'ils disent, pas leurs octets.
 */
export function sameSchema(a: string, b: string): boolean {
  const left = parseSchema(a);
  const right = parseSchema(b);
  if (!left.ok || !right.ok) return a === b;
  return JSON.stringify(left.schema) === JSON.stringify(right.schema);
}
