import type { JsonSchema } from "jsonjoy-builder";

/**
 * L'utilité des champs d'un modèle, portée par le modèle lui-même (Gael, 05/11/2026) :
 * quels champs identifient un objet, et lesquels se montrent dans le tableau du module
 * d'environnement.
 *
 * Écrit à la RACINE du document, sous un mot-clé d'extension, et non sur chaque propriété.
 * Mesuré dans `jsonjoy-builder` 1.0.4 : l'éditeur visuel reconstruit le schéma d'une
 * propriété qu'on modifie (`createFieldSchema`), donc un mot-clé inconnu posé SUR une
 * propriété disparaîtrait au premier passage sur elle — sans message, et sans rien à lire
 * dans le YAML pour comprendre. La racine, elle, est recopiée entière (`updateObjectProperty`).
 *
 * Le méta-schéma 2020-12 admet les mots-clés inconnus : un validateur tiers ignore
 * `x-miles`, et le modèle reste un JSON Schema ordinaire pour qui le lit ailleurs.
 */
export const USAGE_KEYWORD = "x-miles";

/** Les deux utilités déclarables, par chemin de propriété (`$.Id`). */
export interface Usage {
  /** Parties de la clé fonctionnelle, dans l'ordre où elles ont été cochées. */
  key: string[];
  /** Propriétés montrées en colonne dans le tableau des objets. */
  columns: string[];
}

export const NO_USAGE: Usage = { key: [], columns: [] };

export interface RootField {
  name: string;
  /** Jpath, forme déjà employée par les storages : `$.Id`. */
  path: string;
  /** Type déclaré, ou "" quand le champ n'en annonce aucun. */
  type: string;
  /** `$ref` : le champ renvoie à un autre modèle. */
  reference: boolean;
}

// Une clé et une colonne portent UNE valeur : un objet, un tableau ou un renvoi vers un
// autre modèle n'en est pas une. Règle plus stricte que `selectable` de l'arbre des
// storages, qui travaille sur les chemins résolus par le serveur — ici le `$ref` n'est
// pas résolu, et proposer la case ferait découvrir le refus après coup.
const SCALARS = new Set(["string", "number", "integer", "boolean"]);

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Un champ se coche-t-il ? */
export function offerable(field: RootField): boolean {
  return !field.reference && SCALARS.has(field.type);
}

/**
 * Les champs de PREMIER NIVEAU, dans l'ordre du document.
 *
 * Lus dans le schéma en mémoire, et non demandés au serveur : la liste suit ce que
 * l'onglet de l'éditeur montre, y compris avant d'enregistrer. Demander au serveur aurait
 * décrit le modèle ENREGISTRÉ, c'est-à-dire un autre que celui qu'on a sous les yeux.
 */
export function rootFields(schema: JsonSchema): RootField[] {
  const properties = asRecord(asRecord(schema)?.properties);
  if (properties === null) {
    return [];
  }
  return Object.entries(properties).map(([name, value]) => {
    const node = asRecord(value);
    const type = node?.type;
    return {
      name,
      path: `$.${name}`,
      // Un type multiple (`type: [string, "null"]`) n'est pas une valeur simple à
      // déclarer : on garde la chaîne vide, et le champ ne se coche pas.
      type: typeof type === "string" ? type : "",
      reference: typeof node?.$ref === "string",
    };
  });
}

function paths(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

/** Ce que le modèle déclare aujourd'hui ; vide s'il ne déclare rien. */
export function usageOf(schema: JsonSchema): Usage {
  const declared = asRecord(asRecord(schema)?.[USAGE_KEYWORD]);
  if (declared === null) {
    return NO_USAGE;
  }
  return { key: paths(declared.key), columns: paths(declared.columns) };
}

/**
 * Le schéma portant cette utilité, limitée aux champs qui existent ENCORE.
 *
 * L'élagage se fait ici, au moment où l'on écrit, et pas à chaque frappe dans le YAML :
 * un champ qu'on est en train de renommer disparaîtrait au milieu de la saisie. Un nom
 * resté dans le fichier est inerte — il ne décrit aucun champ —, et il s'en va dès qu'on
 * touche à cet écran.
 */
export function withUsage(schema: JsonSchema, usage: Usage): JsonSchema {
  const known = new Set(rootFields(schema).map((field) => field.path));
  const kept: Usage = {
    key: usage.key.filter((path) => known.has(path)),
    columns: usage.columns.filter((path) => known.has(path)),
  };
  // Rien de déclaré : le mot-clé s'en va plutôt que de rester en coquille vide, qu'on
  // lirait dans le YAML comme une déclaration à moitié faite.
  const reste = Object.fromEntries(
    Object.entries(asRecord(schema) ?? {}).filter(([mot]) => mot !== USAGE_KEYWORD),
  );
  if (kept.key.length === 0 && kept.columns.length === 0) {
    return reste as JsonSchema;
  }
  return { ...reste, [USAGE_KEYWORD]: kept } as JsonSchema;
}

/** Le chemin ajouté ou retiré de la liste, sans la réordonner. */
export function toggled(selected: string[], path: string): string[] {
  return selected.includes(path)
    ? selected.filter((item) => item !== path)
    : [...selected, path];
}
