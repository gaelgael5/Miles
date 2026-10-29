import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "./http";
import { request } from "./http";

/**
 * Ce que fait CELUI QUI S'APPARIE : frapper chez le module d'enrôlement, coller le code,
 * constater où en est la demande.
 *
 * Au socle depuis le 29/10/2026, parce qu'un DEUXIÈME produit s'apparie — le module de
 * paramétrage après le module d'environnement (ticket ba44914b, qui interdit nommément
 * d'en dupliquer un second mécanisme). Les routes sont les mêmes, servies par le même
 * code au socle du backend : deux clients d'API de même forme auraient divergé au premier
 * champ ajouté d'un seul côté, et l'écran de l'autre l'aurait ignoré en silence.
 *
 * Ce que le produit garde : ce qu'il tient EN PLUS d'un pair. Le module d'environnement
 * lit l'environnement que l'enrôlement lui assigne, et cette requête est chez lui.
 */

/**
 * Les états que l'administrateur peut rencontrer.
 *
 * « En attente » et « échoué » ne se confondent jamais : un écran qui les mélange fait
 * recommencer la demande indéfiniment, ou fait attendre une acceptation qui ne viendra
 * pas. `pair_injoignable` est distinct des deux — faire recommencer pour une panne de
 * réseau détruirait un appariement en cours d'acceptation.
 */
export type PairingStateName =
  | "non_apparie"
  | "en_attente"
  | "apparie"
  | "refusee"
  | "expiree"
  | "pair_injoignable"
  // Le pair refuse nos appels signés alors qu'on le croit apparié : il a pu révoquer
  // l'appariement de son côté. Distinct de `pair_injoignable`, qui est une panne de
  // réseau et ne remet rien en cause — et distinct de `non_apparie`, parce qu'un
  // appariement a bien existé et que ses informations restent utiles à comparer.
  | "refuse_par_le_pair"
  // Le pair nous a DIT qu'il nous révoquait, par un avis signé qu'on a vérifié — et ses
  // appels nous sont bien refusés depuis. Distinct de `refuse_par_le_pair`, qui est le
  // même refus sans avis : là on énumère les causes, ici on les nomme.
  | "revoque";

export interface PairingAttempt {
  base_url: string;
  created_at: string;
  name: string | null;
  expires_at: string | null;
}

export interface EnrolmentPeer {
  base_url: string;
  /** Le nom que CE module a déclaré — pas celui du pair, qui n'en déclare aucun. */
  declared_name: string | null;
  /**
   * L'adresse où on le JOINT, qui n'est pas son identité. Elle n'entre dans aucune chaîne
   * signée. Égale à `base_url` tant qu'aucun intermédiaire ne s'interpose : l'écran ne la
   * montre alors pas, deux lignes identiques faisant chercher une différence qui n'existe pas.
   */
  contact_url: string;
  /** Quand l'avis de révocation a été reçu. Nul tant qu'il n'est pas venu. */
  revoked_at: string | null;
  public_key: string;
  public_key_fingerprint: string;
  algorithm: string;
  created_at: string;
  updated_at: string;
}

export interface PairingState {
  state: PairingStateName;
  attempt: PairingAttempt | null;
  peer: EnrolmentPeer | null;
}

// Clef partagée par les deux produits : c'est le même état, lu aux mêmes routes.
export const PEERING_KEY = ["peering"] as const;
// Pendant l'attente, l'état vit chez le pair : c'est un humain, là-bas, qui va répondre.
// Sans relecture, l'écran dirait « en attente » longtemps après le refus.
const PENDING_REFRESH_MS = 5000;

export function usePairingState() {
  return useQuery({
    queryKey: [...PEERING_KEY, "state"],
    queryFn: ({ signal }) => request<PairingState>("/api/identity/pairing/state", { signal }),
    refetchInterval: (query) =>
      // Seuls les états qui PEUVENT changer tout seuls sont relus. Appariée ou non
      // appariée, rien ne bougera sans un geste d'ici.
      query.state.data?.state === "en_attente" || query.state.data?.state === "pair_injoignable"
        ? PENDING_REFRESH_MS
        : false,
  });
}

function usePairingMutation<I, O>(mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    // L'état se relit au serveur : l'attente vit là-bas, jamais dans cet onglet.
    onSettled: () => client.invalidateQueries({ queryKey: PEERING_KEY }),
  });
}

export function useRequestPairing() {
  return usePairingMutation((input: { base_url: string; name: string }) =>
    request<PairingAttempt>("/api/identity/pairing", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
}

export function useConfirmPairing() {
  return usePairingMutation((code: string) =>
    request<EnrolmentPeer>("/api/identity/pairing/confirm", {
      method: "POST",
      // Nettoyé ici : un code circule par copier-coller, il arrive avec des espaces et
      // parfois un retour à la ligne. Le refuser pour cela serait refuser le bon code.
      body: JSON.stringify({ code: code.replace(/\s+/g, "") }),
    }),
  );
}

export function useCancelPairing() {
  return usePairingMutation(() =>
    request<undefined>("/api/identity/pairing", { method: "DELETE" }),
  );
}

/**
 * La dérive d'horloge annoncée par le pair, en secondes, quand c'est elle qui a refusé.
 *
 * `null` dans tous les autres cas, y compris quand le pair dit « horloges » sans donner
 * de nombre lisible : l'écran retombe alors sur le refus générique plutôt que d'afficher
 * une dérive inventée. Le nombre vient d'un AUTRE service — il est typé avant d'être cru.
 */
export function clockDrift(error: unknown): number | null {
  if (!(error instanceof ApiError) || error.detail !== "horloges_desynchronisees") {
    return null;
  }
  const derive = error.payload.drift_s;
  return typeof derive === "number" && Number.isFinite(derive) ? Math.round(derive) : null;
}
