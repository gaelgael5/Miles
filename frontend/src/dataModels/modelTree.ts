import { YAMLParseError, parse, stringify } from "yaml";

/**
 * Le modèle de données tel que l'arbre le manipule (story 7208ba06). Le serveur reste
 * l'arbitre de la grammaire : l'arbre ne représente que ce qu'il sait réécrire sans
 * rien perdre, et refuse de s'ouvrir sur le reste plutôt que de l'effacer en silence.
 */
export const SCALAR_TYPES = ["chaine", "entier", "decimal", "booleen", "date", "horodatage"] as const;
export const TYPES = [...SCALAR_TYPES, "enumeration", "objet", "liste"] as const;
export type PropType = (typeof TYPES)[number];
// Même borne que la grammaire du serveur : une liste de listes s'arrête là.
export const MAX_LIST_DEPTH = 4;
export const PROPERTY_RE = /^[a-z][a-z0-9_]{0,62}$/;

export interface TypeSpec {
  type: PropType;
  valeurs?: string[];
  modele?: string;
  elements?: TypeSpec;
}

export interface PropertyNode extends TypeSpec {
  // Stable le temps de l'édition : la clé React ne suit pas le nom, qu'on renomme.
  id: string;
  name: string;
  obligatoire: boolean;
}

export interface ModelDoc {
  nom: string;
  version: number;
  description?: string;
  proprietes: PropertyNode[];
}

export type Parsed =
  | { ok: true; doc: ModelDoc }
  | { ok: false; reason: "syntax"; line: number | null; column: number | null; message: string }
  // Lisible, mais hors de ce que l'arbre sait réécrire : `path` dit où.
  | { ok: false; reason: "shape"; path: string };

let nextId = 0;
export function newId(): string {
  nextId += 1;
  return `p${nextId}`;
}

const TOP_KEYS = new Set(["nom", "version", "description", "proprietes"]);
const SPEC_KEYS = new Set(["type", "valeurs", "modele", "elements"]);

class ShapeError extends Error {
  constructor(readonly path: string) {
    super(path);
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readSpec(raw: unknown, path: string, extra: Set<string>, depth: number): TypeSpec {
  if (!isObject(raw)) throw new ShapeError(path);
  for (const key of Object.keys(raw)) {
    if (!SPEC_KEYS.has(key) && !extra.has(key)) throw new ShapeError(`${path}.${key}`);
  }
  const type = raw.type;
  if (typeof type !== "string" || !(TYPES as readonly string[]).includes(type)) {
    throw new ShapeError(`${path}.type`);
  }
  const spec: TypeSpec = { type: type as PropType };
  if (type === "enumeration") {
    const values = raw.valeurs;
    if (!Array.isArray(values) || !values.every((v) => typeof v === "string")) {
      throw new ShapeError(`${path}.valeurs`);
    }
    spec.valeurs = values as string[];
  } else if (type === "objet") {
    if (typeof raw.modele !== "string") throw new ShapeError(`${path}.modele`);
    spec.modele = raw.modele;
  } else if (type === "liste") {
    if (depth >= MAX_LIST_DEPTH) throw new ShapeError(`${path}.elements`);
    spec.elements = readSpec(raw.elements, `${path}.elements`, new Set(), depth + 1);
  }
  return spec;
}

function readDoc(data: unknown): ModelDoc {
  if (!isObject(data)) throw new ShapeError("/");
  for (const key of Object.keys(data)) {
    if (!TOP_KEYS.has(key)) throw new ShapeError(key);
  }
  if (typeof data.nom !== "string") throw new ShapeError("nom");
  if (typeof data.version !== "number" || !Number.isInteger(data.version)) {
    throw new ShapeError("version");
  }
  if (data.description !== undefined && typeof data.description !== "string") {
    throw new ShapeError("description");
  }
  const raw = data.proprietes ?? {};
  if (!isObject(raw)) throw new ShapeError("proprietes");
  const proprietes = Object.entries(raw).map(([name, spec]): PropertyNode => {
    const path = `proprietes.${name}`;
    const read = readSpec(spec, path, new Set(["obligatoire"]), 0);
    const required = isObject(spec) ? spec.obligatoire : undefined;
    if (required !== undefined && typeof required !== "boolean") {
      throw new ShapeError(`${path}.obligatoire`);
    }
    return { ...read, id: newId(), name, obligatoire: required === true };
  });
  return {
    nom: data.nom,
    version: data.version,
    ...(data.description !== undefined ? { description: data.description } : {}),
    proprietes,
  };
}

export function parseModel(text: string): Parsed {
  let data: unknown;
  try {
    data = parse(text, { uniqueKeys: true });
  } catch (error) {
    if (error instanceof YAMLParseError) {
      const at = error.linePos?.[0];
      return {
        ok: false,
        reason: "syntax",
        line: at?.line ?? null,
        column: at?.col ?? null,
        message: error.message.split("\n")[0] ?? "",
      };
    }
    throw error;
  }
  try {
    return { ok: true, doc: readDoc(data) };
  } catch (error) {
    if (error instanceof ShapeError) return { ok: false, reason: "shape", path: error.path };
    throw error;
  }
}

function writeSpec(spec: TypeSpec): Record<string, unknown> {
  const out: Record<string, unknown> = { type: spec.type };
  if (spec.type === "enumeration") out.valeurs = spec.valeurs ?? [];
  if (spec.type === "objet") out.modele = spec.modele ?? "";
  if (spec.type === "liste") out.elements = writeSpec(spec.elements ?? { type: "chaine" });
  return out;
}

/** Le YAML que l'arbre produit ; l'ordre des clés suit celui de la grammaire. */
export function serializeModel(doc: ModelDoc): string {
  const proprietes: Record<string, unknown> = {};
  for (const node of doc.proprietes) {
    proprietes[node.name] = {
      ...writeSpec(node),
      ...(node.obligatoire ? { obligatoire: true } : {}),
    };
  }
  const data = {
    nom: doc.nom,
    version: doc.version,
    ...(doc.description ? { description: doc.description } : {}),
    proprietes,
  };
  return stringify(data, { lineWidth: 0 });
}

/** Changer de type remet à neuf ce qui lui est propre : rien ne survit d'un autre type. */
export function retype(type: PropType): TypeSpec {
  if (type === "enumeration") return { type, valeurs: [] };
  if (type === "objet") return { type, modele: "" };
  if (type === "liste") return { type, elements: { type: "chaine" } };
  return { type };
}

export function freeName(doc: ModelDoc): string {
  const taken = new Set(doc.proprietes.map((p) => p.name));
  let index = 1;
  while (taken.has(`propriete_${index}`)) index += 1;
  return `propriete_${index}`;
}

export function addProperty(doc: ModelDoc): ModelDoc {
  const node: PropertyNode = { id: newId(), name: freeName(doc), type: "chaine", obligatoire: false };
  return { ...doc, proprietes: [...doc.proprietes, node] };
}

export function removeProperty(doc: ModelDoc, id: string): ModelDoc {
  return { ...doc, proprietes: doc.proprietes.filter((p) => p.id !== id) };
}

export function updateProperty(doc: ModelDoc, id: string, patch: Partial<PropertyNode>): ModelDoc {
  return { ...doc, proprietes: doc.proprietes.map((p) => (p.id === id ? { ...p, ...patch } : p)) };
}

export function retypeProperty(doc: ModelDoc, id: string, type: PropType): ModelDoc {
  return {
    ...doc,
    proprietes: doc.proprietes.map((p) =>
      p.id === id ? { id: p.id, name: p.name, obligatoire: p.obligatoire, ...retype(type) } : p,
    ),
  };
}

/** Remplace tout ce qui type la propriété : rien d'un type précédent ne survit. */
export function setSpec(doc: ModelDoc, id: string, spec: TypeSpec): ModelDoc {
  return {
    ...doc,
    proprietes: doc.proprietes.map((p) =>
      p.id === id ? { id: p.id, name: p.name, obligatoire: p.obligatoire, ...spec } : p,
    ),
  };
}
