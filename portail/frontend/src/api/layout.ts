import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@miles/socle-web";

import { atBranch, branchKey, type WorkTarget } from "./workTarget";

/**
 * La disposition du dépôt de paramétrage sur une branche (story d781001a).
 *
 * Lue même quand la branche est refusée à l'ouverture : c'est elle qui permet d'annoncer
 * le refus et d'offrir le geste qui le lève. Sans elle, l'écran recevait « convertissez
 * cette branche » sans aucun moyen de convertir — relevé par Gael le 15/11/2026.
 */
export interface BranchLayout {
  /** `a_jour`, `ancienne` ou `melangee`. */
  kind: string;
  /** Le motif de refus d'ouverture, ou null quand la branche s'ouvre. */
  refusal: string | null;
  /** Ce que la conversion écrirait : des nombres, annoncés avant le clic. */
  moves: number;
  event_types: number;
  /** Les chemins qu'un ex-event et un modèle se disputent : la conversion s'y arrête. */
  conflicts: string[];
}

export function useBranchLayout(target: WorkTarget) {
  return useQuery({
    queryKey: branchKey("layout", target),
    queryFn: ({ signal }) => request<BranchLayout>(atBranch(target, "layout"), { signal }),
  });
}

export function useConvertLayout(target: WorkTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<{ moved: number }>(atBranch(target, "layout", "convert"), { method: "POST" }),
    // Tout ce qui était refusé sur cette branche redevient lisible : on ne cible pas les
    // vues une à une, parce qu'une vue oubliée resterait sur son refus jusqu'au
    // rechargement de la page, et ressemblerait à une conversion qui n'a rien fait.
    onSuccess: () => client.invalidateQueries(),
  });
}
