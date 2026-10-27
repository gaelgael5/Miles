import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, request } from "./http";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/** Trois colonnes au plus par index (Gael, 24/10/2026) ; autant d'index que nécessaire. */
export const MAX_COLUMNS = 3;

/**
 * Un index additionnel : son nom figé fait son identifiant, jamais un hash des colonnes.
 * L'ordre des colonnes compte — c'est celui d'un index composite.
 */
export interface Index {
  name: string;
  columns: string[];
}

/**
 * Déclaration d'un storage (story 844f15ad), stockée dans la branche : la collection
 * d'objets, son modèle, sa clé fonctionnelle et ce sur quoi on pourra la filtrer.
 *
 * Notion distincte de la source de données (Gael, 24/10/2026) : un storage s'alimente
 * aussi par API ou par MCP, et la source ne fait que le désigner.
 */
export interface Storage {
  /** Identifiant : il nomme le fichier, et se déduit du libellé à la création. */
  name: string;
  /** Ce que la personne a écrit, et ce que les écrans affichent. */
  label: string;
  /** « portée/nom » du modèle des objets stockés. */
  model: string;
  /** Jpath évalués sur l'objet STOCKÉ, qui l'identifient d'une écriture à l'autre. */
  keys: string[];
  indexes: Index[];
}

export interface SavedStorage extends Storage {
  /** Modèle ou index changés : le prochain import réécrira objets et index. */
  rewrite_announced: boolean;
}

export interface StorageSummary {
  name: string;
  /** null : déclaration illisible, retouchée hors de Miles. */
  label: string | null;
  model: string | null;
  keys: string[] | null;
}

/** Un défaut de la déclaration, désigné par son chemin (« index[1].colonnes[0] »…). */
export interface StorageProblem {
  path: string;
  code: string;
  detail: string | null;
}

/** Les défauts d'un refus `storage_invalide` ; vide pour tout autre échec. */
export function storageProblems(error: unknown): StorageProblem[] {
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail !== null) {
    const detail = error.detail as { code?: string; problems?: StorageProblem[] };
    if (detail.code === "storage_invalide") {
      return detail.problems ?? [];
    }
  }
  return [];
}

/** Les sources qui empêchent la suppression, nommées par le refus `storage_utilise`. */
export function storageUsers(error: unknown): string[] {
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail !== null) {
    const detail = error.detail as { code?: string; sources?: string[] };
    if (detail.code === "storage_utilise") {
      return detail.sources ?? [];
    }
  }
  return [];
}

function key(target: WorkTarget) {
  return branchKey("storages", target);
}

export function useStorages(target: WorkTarget) {
  return useQuery({
    queryKey: key(target),
    queryFn: ({ signal }) => request<StorageSummary[]>(atBranch(target, "storages"), { signal }),
  });
}

export function useStorage(target: WorkTarget, name: string) {
  return useQuery({
    queryKey: [...key(target), name],
    queryFn: ({ signal }) => request<Storage>(atBranch(target, "storages", name), { signal }),
  });
}

/** Déclare (name absent) ou modifie le storage nommé. */
export function useSaveStorage(target: WorkTarget, name?: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (storage: Storage) =>
      request<SavedStorage>(
        name === undefined ? atBranch(target, "storages") : atBranch(target, "storages", name),
        { method: name === undefined ? "POST" : "PUT", body: JSON.stringify(storage) },
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}

export function useDeleteStorage(target: WorkTarget, name: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<undefined>(atBranch(target, "storages", name), { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}
