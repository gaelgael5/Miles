import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, request } from "@miles/socle-web";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/** Ce que le dépôt reproche au réglage : fichier illisible, ou storage disparu. */
export interface ReferenceProblem {
  path: string;
  code: string;
  detail: string | null;
}

/** Par quel mode part le code d'enregistrement, et vers quel champ du compte. */
export interface Delivery {
  /** Un des `modes` rendus par le serveur ; seuls les `served_modes` sont acceptés. */
  mode: string;
  /** Jpath d'une propriété du modèle du storage, choisi dans une liste, jamais saisi. */
  field: string;
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
  /** null : le stockage est désigné, l'envoi ne l'est pas encore. Pas une erreur. */
  delivery: Delivery | null;
  problem: ReferenceProblem | null;
  /** Les modes connus, et ceux réellement servis. Rendus par le serveur et JAMAIS
   *  codés ici : l'écran ne peut donc pas proposer un mode qu'il refuserait. */
  modes: string[];
  served_modes: string[];
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

/** Ce que le serveur reproche à l'envoi saisi, et ce qu'il fallait. */
export function deliveryRefusal(
  error: unknown,
): { code: string; detail: string | null; servis: string[] } | null {
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail !== null) {
    const detail = error.detail as { code?: string; detail?: string; servis?: string[] };
    if (detail.code !== undefined && detail.code !== "storage_inconnu") {
      return { code: detail.code, detail: detail.detail ?? null, servis: detail.servis ?? [] };
    }
  }
  return null;
}

/**
 * Pose la référence ENTIÈRE. PUT : une branche n'a qu'UNE référence de compte, et
 * `delivery` omis efface l'envoi — fusionner avec l'existant ferait qu'aucun appel ne
 * saurait le retirer.
 */
export function useSetAccountReference(target: WorkTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { storage: string; delivery: Delivery | null }) =>
      request<AccountReference>(atBranch(target, "account-reference"), {
        method: "PUT",
        body: JSON.stringify(body),
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
