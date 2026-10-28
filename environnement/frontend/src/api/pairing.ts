import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, request } from "@miles/socle-web";

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
  | "pair_injoignable";

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

const PAIRING_KEY = ["pairing"] as const;
// Pendant l'attente, l'état vit chez le pair : c'est un humain, là-bas, qui va répondre.
// Sans relecture, l'écran dirait « en attente » longtemps après le refus.
const PENDING_REFRESH_MS = 5000;

export function usePairingState() {
  return useQuery({
    queryKey: [...PAIRING_KEY, "state"],
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
    onSettled: () => client.invalidateQueries({ queryKey: PAIRING_KEY }),
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
