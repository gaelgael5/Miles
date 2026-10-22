import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, request } from "./http";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/** Une propriété filtrable : son nom figé fait son identifiant d'index, pas son jpath. */
export interface Filterable {
  name: string;
  jpath: string;
}

/** Déclaration d'une source de données (story 66391afe), stockée dans la branche. */
export interface Source {
  name: string;
  /** « scope/nom » du modèle cible. */
  model: string;
  /** Jpath du tableau d'items, streamable. */
  split: string;
  keys: string[];
  /** Slug de la chaîne de transformations appliquée à chaque item. */
  chain: string;
  large_file: boolean;
  unified_transaction: boolean;
  filterables: Filterable[];
}

export interface SavedSource extends Source {
  /** Chaîne ou filtrables changés : le prochain import réécrira tous les objets. */
  rewrite_announced: boolean;
}

export interface SourceSummary {
  name: string;
  /** null : déclaration illisible, retouchée hors de Miles. */
  model: string | null;
  chain: string | null;
}

/** Un défaut de la déclaration, désigné par son chemin (« filtrables[1].jpath »…). */
export interface SourceProblem {
  path: string;
  code: string;
  detail: string | null;
}

/** Les défauts d'un refus `source_invalide` ; vide pour tout autre échec. */
export function sourceProblems(error: unknown): SourceProblem[] {
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail !== null) {
    const detail = error.detail as { code?: string; problems?: SourceProblem[] };
    if (detail.code === "source_invalide") {
      return detail.problems ?? [];
    }
  }
  return [];
}

function key(target: WorkTarget) {
  return branchKey("sources", target);
}

export function useSources(target: WorkTarget) {
  return useQuery({
    queryKey: key(target),
    queryFn: ({ signal }) => request<SourceSummary[]>(atBranch(target, "sources"), { signal }),
  });
}

export function useSource(target: WorkTarget, name: string) {
  return useQuery({
    queryKey: [...key(target), name],
    queryFn: ({ signal }) => request<Source>(atBranch(target, "sources", name), { signal }),
  });
}

/** Déclare (name absent) ou modifie la source nommée. */
export function useSaveSource(target: WorkTarget, name?: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (source: Source) =>
      request<SavedSource>(
        name === undefined ? atBranch(target, "sources") : atBranch(target, "sources", name),
        { method: name === undefined ? "POST" : "PUT", body: JSON.stringify(source) },
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}

export function useDeleteSource(target: WorkTarget, name: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<undefined>(atBranch(target, "sources", name), { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}
