import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@miles/socle-web";

import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/**
 * Contextes du référentiel de traductions (story 623898d1) : les répertoires de `trads/`
 * sur la branche regardée. Aucune liste en base — le dépôt fait foi, et un répertoire
 * créé à la main apparaît comme les autres.
 */
export interface TradsContext {
  /** Nom du répertoire `trads/<name>/`, figé après création. */
  name: string;
  /** Pour l'humain seulement ; le nom technique à défaut. */
  label: string;
  keys: number;
  /** Clés traduites par culture du workspace ; rapporté à `keys`, c'est la couverture. */
  translated: Record<string, number>;
  /**
   * Cultures retirées du workspace dont le dépôt garde encore un fichier, et le nombre de
   * valeurs de chacune. Retirer une culture ne détruit rien — c'est voulu —, mais sans ce
   * compte personne ne saurait que ces fichiers existent encore.
   */
  obsolete: Record<string, number>;
}

/** Ce qu'une suppression emporterait : la confirmation l'annonce avant de la demander. */
export interface Removal {
  keys: number;
  values: number;
}

const KIND = "trads";

export function useTradsContexts(target: WorkTarget) {
  return useQuery({
    queryKey: branchKey(KIND, target),
    queryFn: ({ signal }) =>
      request<TradsContext[]>(atBranch(target, KIND), { signal }),
  });
}

export function useRemovalPreview(target: WorkTarget, name: string | null) {
  return useQuery({
    queryKey: [...branchKey(KIND, target), name, "removal"],
    // Demandé seulement quand une suppression est envisagée : sinon l'écran lirait le
    // dépôt une fois par ligne, à chaque affichage de la liste.
    enabled: name !== null,
    queryFn: ({ signal }) =>
      request<Removal>(atBranch(target, KIND, name ?? "", "removal"), { signal }),
  });
}

export function useAddTradsContext(target: WorkTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; label: string }) =>
      request<TradsContext>(atBranch(target, KIND), {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: branchKey(KIND, target) }),
  });
}

/** Change le LIBELLÉ. Le nom technique n'a aucune route : il est figé après création. */
export function useRelabelTradsContext(target: WorkTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { name: string; label: string }) =>
      request<TradsContext>(atBranch(target, KIND, input.name), {
        method: "PUT",
        body: JSON.stringify({ label: input.label }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: branchKey(KIND, target) }),
  });
}

/** Retire le fichier d'une culture que le workspace ne retient plus. */
export function useCleanObsoleteCulture(target: WorkTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { context: string; culture: string }) =>
      request<Removal>(atBranch(target, KIND, input.context, "obsolete", input.culture), {
        method: "DELETE",
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: branchKey(KIND, target) }),
  });
}

export function useDeleteTradsContext(target: WorkTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      request<Removal>(atBranch(target, KIND, name), { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: branchKey(KIND, target) }),
  });
}

/** Le nom technique proposé depuis le libellé : mêmes caractères que sur le serveur. */
export function contextNameFrom(label: string): string {
  return label
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}
