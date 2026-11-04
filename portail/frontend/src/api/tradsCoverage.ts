import { useQuery } from "@tanstack/react-query";
import { request } from "@miles/socle-web";

import type { TradsContext } from "./trads";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/** Ce qu'une culture du workspace a de traduit sur la branche regardée. */
export interface CultureCoverage {
  culture: string;
  translated: number;
  missing: number;
  /**
   * La culture par défaut du WORKSPACE, qu'une clé ne peut pas ne pas porter. Donnée par
   * le serveur et jamais déduite du code : elle n'est `en-US` que sur un workspace qui
   * n'en a pas changé, et l'écran qui la coderait en dur mentirait sur tous les autres.
   */
  is_default: boolean;
  /** Sous le seuil, donc signalée. Jamais vrai pour la culture par défaut. */
  low: boolean;
  /** Des clés sans valeur dans la culture par défaut : le DÉPÔT est incohérent. */
  inconsistent: boolean;
}

export interface TradsCoverage {
  /** La branche que le serveur a réellement lue, pas celle demandée. */
  branch: string;
  default: string;
  keys: number;
  /** Le seuil appliqué, en pour cent : l'écran annonce le signalement avec sa borne. */
  threshold: number;
  cultures: CultureCoverage[];
  contexts: TradsContext[];
}

export function useTradsCoverage(target: WorkTarget) {
  return useQuery({
    // Sous la clé des contextes : créer, renommer ou supprimer un contexte invalide
    // `["trads", workspace, branche]`, et TanStack invalide par PRÉFIXE — la couverture
    // suit donc les gestes de l'autre écran sans qu'aucun d'eux ne la connaisse.
    queryKey: [...branchKey("trads", target), "coverage"],
    queryFn: ({ signal }) =>
      request<TradsCoverage>(atBranch(target, "trads", "coverage"), { signal }),
  });
}

/** Le taux de couverture, entier. Zéro clé : cent pour cent serait une bonne nouvelle
 * fausse, et zéro une mauvaise — l'écran dit « vide » et n'affiche aucun taux. */
export function percentOf(translated: number, keys: number): number | null {
  return keys === 0 ? null : Math.round((translated * 100) / keys);
}
