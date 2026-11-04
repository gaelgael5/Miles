import { useQuery } from "@tanstack/react-query";
import { request } from "@miles/socle-web";

import { KEY_COLUMN, encodedKey } from "./storageKey";

/**
 * Les espaces de stockage de cette stack, tels que la version servie les déclare.
 *
 * Lecture seule, et aucune mutation n'existera ici : ce qu'un storage EST vient du
 * paramétrage versionné, choisi dans le module de paramétrage et servi par la version
 * que l'enrôlement a placée. Un écran qui le modifierait créerait une seconde source
 * pour la même décision.
 */
export interface Projection {
  column: string;
  /** Le chemin DÉCLARÉ, celui que la personne a choisi dans l'arbre des propriétés. */
  path: string;
  kind: string;
  sql_type: string;
}

export interface StorageIndex {
  name: string;
  columns: string[];
}

export interface Storage {
  name: string;
  label: string;
  model: string;
  schema_name: string;
  table_name: string;
  keys: string[];
  projections: Projection[];
  indexes: StorageIndex[];
  /** Nuls tant que la table n'est pas posée : l'écran doit pouvoir le dire. */
  applied_at: string | null;
  version_number: number | null;
  refusal: string | null;
  refusal_detail: string | null;
}

export interface StorageObject {
  cle: string;
  objet: Record<string, unknown>;
  vu_le: string;
  modifie_le: string;
  origine: string;
  /** Les colonnes projetées de cet objet : elles disent pourquoi il est dans le résultat. */
  columns: Record<string, unknown>;
}

export interface ObjectPage {
  objects: StorageObject[];
  total: number;
  page: number;
  page_size: number;
}

/** Un critère de recherche, tel que l'écran le compose et que l'API l'attend. */
export interface Criterion {
  column: string;
  operator: string;
  value: string;
}

/**
 * Les comparaisons offertes, par famille de type SQL — et rien d'autre.
 *
 * « contient » d'abord : c'est l'opérateur par DÉFAUT d'une colonne de texte (Gael,
 * 04/11/2026), parce qu'on cherche un fragment bien plus souvent qu'une valeur exacte.
 * Les comparaisons textuelles ne sont pas offertes sur un nombre ou un booléen : le
 * serveur les refuse, et proposer ici ce qui sera refusé là-bas ferait découvrir le
 * refus après coup.
 */
export const OPERATORS: Record<string, readonly string[]> = {
  text: ["contient", "prefixe", "eq", "ne"],
  bigint: ["eq", "ne", "gt", "ge", "lt", "le"],
  numeric: ["eq", "ne", "gt", "ge", "lt", "le"],
  boolean: ["eq", "ne"],
};

/** Les comparaisons offertes sur cette colonne, la première étant celle par défaut. */
export function operatorsFor(sqlType: string): readonly string[] {
  return OPERATORS[sqlType] ?? OPERATORS.text ?? [];
}

export function useStorages() {
  return useQuery({
    queryKey: ["storages"],
    queryFn: ({ signal }) => request<Storage[]>("/api/storages", { signal }),
  });
}

/**
 * Les objets d'un storage. La clé de cache porte les critères : revenir à une recherche
 * déjà faite la réaffiche sans attendre, et en changer un seul la relance.
 *
 * `enabled` permet de ne rien demander tant qu'aucun storage n'est choisi — et de ne pas
 * interroger un storage refusé, dont la table peut ne pas exister.
 */
export function useStorageObjects(
  name: string,
  criteria: Criterion[],
  page: number,
  enabled: boolean,
) {
  // Un critère sans valeur n'est pas un critère : la barre de filtres porte une colonne
  // par propriété filtrable, et la plupart restent vides.
  const f = criteria
    .filter((c) => c.column !== "" && c.value !== "")
    .map((c) => `${c.column}:${c.operator}:${searchedValue(c)}`);
  const params = new URLSearchParams();
  for (const critere of f) {
    params.append("f", critere);
  }
  params.set("page", String(page));
  return useQuery({
    queryKey: ["storages", name, "objects", f, page],
    enabled,
    queryFn: ({ signal }) =>
      request<ObjectPage>(`/api/storages/${encodeURIComponent(name)}/objects?${params}`, {
        signal,
      }),
  });
}

/** Ce qui part au serveur : ce qui a été tapé, sauf sur la clé, qui a sa forme. */
function searchedValue(criterion: Criterion): string {
  return criterion.column === KEY_COLUMN
    ? encodedKey(criterion.value, criterion.operator)
    : criterion.value;
}
