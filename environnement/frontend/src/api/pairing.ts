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

/**
 * L'environnement du référentiel auquel le module d'enrôlement nous a rattachés.
 *
 * Le seul nom qui fasse AUTORITÉ sur cet environnement : il est posé par un humain chez
 * l'enrôlement, alors que `declared_name` est ce que cette stack dit d'elle-même. Les deux
 * peuvent différer, et c'est celui-ci qui compte.
 *
 * `fetched_at` voyage AVEC la valeur, parce qu'une valeur venue d'un autre module ne
 * s'affiche jamais sans la date à laquelle on l'a obtenue : sans elle, un repli serait
 * indiscernable d'une lecture fraîche.
 */
export interface AssignedEnvironment {
  slug: string;
  label: string;
  fetched_at: string;
}

export interface AssignedEnvironmentView {
  environment: AssignedEnvironment | null;
  /**
   * Vrai quand la valeur vient d'être relue chez le pair. Ne se déduit PAS de
   * `environment` : « le pair est injoignable et on n'a jamais rien su » et « le pair dit
   * qu'aucun environnement ne nous est rattaché » rendent tous deux `environment: null`,
   * et les confondre annoncerait « aucun environnement » à un administrateur dont le
   * réseau est coupé.
   */
  fresh: boolean;
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

/**
 * L'environnement assigné, relu CHEZ LE PAIR à chaque affichage.
 *
 * Sa propre requête, et non un champ de l'état d'appariement : les deux émettent chacune
 * un appel signé vers le pair, et les fondre ferait échouer l'une avec l'autre. L'écran
 * veut au contraire pouvoir dire « apparié, mais l'environnement n'a pas pu être rafraîchi ».
 *
 * Aucune relecture périodique : ce nom ne change que par un geste humain à l'autre bout,
 * et le serveur paie un appel sortant à chaque lecture.
 */
export function useAssignedEnvironment() {
  return useQuery({
    queryKey: [...PAIRING_KEY, "environment"],
    queryFn: ({ signal }) =>
      request<AssignedEnvironmentView>("/api/identity/environment", { signal }),
  });
}
