import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, request } from "@miles/socle-web";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/** Ce que le dépôt reproche au réglage : fichier illisible, ou storage disparu. */
export interface ReferenceProblem {
  path: string;
  code: string;
  detail: string | null;
}

/**
 * La référence de compte d'une branche (story a3ece1e9) : LE storage dont les objets
 * sont les comptes associés aux devices.
 *
 * Pas de modèle à choisir — correction de Gael du 31/10/2026, « c'est le stockage que
 * l'on déclare, donc c'est juste une liste déroulante ». Le `model` rendu ici est LU
 * dans le storage désigné : il s'affiche, il ne se saisit pas, et il n'est jamais écrit
 * dans le fichier de référence, qui n'aurait aucun moyen de le voir changer.
 */
export interface AccountReference {
  /** null : aucune référence déclarée sur cette branche. Ce n'est pas une erreur. */
  storage: string | null;
  /** null quand il n'y a pas de référence, ou que le storage a disparu de la branche. */
  model: string | null;
  problem: ReferenceProblem | null;
}

/** Les storages que la branche porte, quand celui qu'on a nommé n'en est pas. */
export function unknownStorages(error: unknown): string[] {
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail !== null) {
    const detail = error.detail as { code?: string; existants?: string[] };
    if (detail.code === "storage_inconnu") {
      return detail.existants ?? [];
    }
  }
  return [];
}

function key(target: WorkTarget) {
  return branchKey("account-reference", target);
}

export function useAccountReference(target: WorkTarget) {
  return useQuery({
    queryKey: key(target),
    queryFn: ({ signal }) =>
      request<AccountReference>(atBranch(target, "account-reference"), { signal }),
  });
}

/** Désigne le storage. PUT : une branche n'a qu'UNE référence de compte. */
export function useSetAccountReference(target: WorkTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (storage: string) =>
      request<AccountReference>(atBranch(target, "account-reference"), {
        method: "PUT",
        body: JSON.stringify({ storage }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}

export function useRemoveAccountReference(target: WorkTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<undefined>(atBranch(target, "account-reference"), { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}
