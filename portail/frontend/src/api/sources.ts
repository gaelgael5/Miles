import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, request } from "@miles/socle-web";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/** Plafond du mode tableau (Gael, 25/10/2026) ; le backend l'applique, voir MAX_BATCH. */
export const MAX_BATCH = 200;

/** Lectures avant enregistrement par défaut ; miroir de DEFAULT_WRITE_BATCH du backend. */
export const DEFAULT_WRITE_BATCH = 100;

/** Les méthodes exposées par une entrée. Au moins une, sinon elle n'expose rien. */
export interface EntryModes {
  /** Un objet du modèle source, pour les intégrations à l'unité. */
  element: boolean;
  /** Un tableau d'objets du modèle source, MAX_BATCH au plus. */
  batch: boolean;
  /** Un fichier déposé, rangé en temporaire puis lu en flux selon le découpage. */
  file: boolean;
}

/** Une entrée : par quel moyen la donnée arrive, et ce qu'elle traverse. */
export interface SourceEntry {
  /** « web » à ce jour ; écrit plutôt que sous-entendu, pour qu'un second type s'ajoute. */
  kind: string;
  /** « portée/nom » du modèle qui arrive sur la méthode. */
  source_model: string;
  /** Slug de la chaîne qui mène du modèle source au modèle du storage. */
  chain: string;
  modes: EntryModes;
  /** Où sont les items dans le fichier déposé. Requis par le seul mode fichier. */
  split: string;
  /** Une seule transaction pour tout l'import, ou une par lot écrit. */
  unified_transaction: boolean;
  /**
   * Lectures consécutives avant enregistrement (Gael, 25/10/2026). Il dit TOUS LES
   * COMBIEN on écrit ; la transaction unifiée dit QUAND on valide. Indépendants.
   */
  write_batch: number;
}

/**
 * Déclaration d'une source de données (story 66391afe, refondue le 25/10/2026) : une
 * ENTRÉE de données dans l'application. Elle dit d'abord OÙ ça va — la donnée cible —
 * et c'est tout ce qu'il faut pour l'enregistrer ; elle porte ensuite ses entrées.
 */
export interface Source {
  /** Identifiant : il nomme le fichier, et se déduit du libellé à la création. */
  name: string;
  /** Ce que la personne a écrit, et ce que les écrans affichent. */
  label: string;
  /** La donnée cible : le storage où les objets atterrissent. */
  storage: string;
  entries: SourceEntry[];
}

export interface SavedSource extends Source {
  /** Une entrée a changé : le prochain import réécrira tous les objets. */
  rewrite_announced: boolean;
}

export interface SourceSummary {
  name: string;
  /** null : déclaration illisible, retouchée hors de Miles. */
  label: string | null;
  storage: string | null;
  entries: number | null;
}

/** Un défaut de la déclaration, désigné par son chemin (« storage », « decoupage »…). */
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
