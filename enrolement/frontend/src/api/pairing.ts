import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, request } from "@miles/socle-web";

/**
 * L'environnement du référentiel, vu depuis l'appariement : juste de quoi le nommer.
 *
 * L'identifiant est STABLE, le slug et le libellé sont renommables : l'écran affiche les
 * seconds et renvoie le premier.
 */
export interface EnvironmentRef {
  id: string;
  slug: string;
  label: string;
}

/** Une demande d'appariement en attente du geste humain. Jamais son secret. */
export interface PairingRequest {
  base_url: string;
  /**
   * Texte libre déclaré par le demandeur, que PERSONNE n'a encore authentifié. Il aide à
   * reconnaître la demande qu'on accepte, et n'identifie rien : deux demandes peuvent
   * porter le même, seule l'URL les distingue. Nul pour une demande antérieure au nom
   * déclaré. React l'échappe à l'affichage — ne jamais le passer à `dangerouslySetInnerHTML`.
   */
  name: string | null;
  public_key_fingerprint: string;
  algorithm: string;
  created_at: string;
  expires_at: string;
  /**
   * L'environnement DÉSIGNÉ par un humain authentifié. Nul tant que personne n'a choisi,
   * et c'est alors le code qui n'est pas révélable. À ne pas confondre avec `name`
   * ci-dessus : l'un vient d'un inconnu et aide à reconnaître, l'autre désigne.
   */
  environment: EnvironmentRef | null;
}

export interface PairedEnvironment {
  base_url: string;
  name: string | null;
  public_key: string;
  public_key_fingerprint: string;
  algorithm: string;
  created_at: string;
  updated_at: string;
  /** Nul tant que le référentiel des devices n'existe pas : l'écran affiche « — ». */
  device_count: number | null;
  /**
   * L'adresse où JOINDRE cette stack, saisie ici. Elle n'entre dans aucune signature et
   * ne vaut jamais identité : l'origine déclarée d'un appel entrant se compare à
   * `base_url`, et à elle seule. Égale à `base_url` tant qu'aucun intermédiaire ne
   * s'interpose — l'écran ne la montre alors pas.
   */
  contact_url: string;
  /**
   * Nul UNIQUEMENT pour les appariements hérités, conclus avant que la désignation
   * n'existe : l'écran les signale « à rattacher ». Aucun appariement neuf ne peut plus
   * se conclure sans — c'est un état transitoire hérité, pas un état admis.
   */
  environment: EnvironmentRef | null;
}

export interface PairingCode {
  base_url: string;
  code: string;
  seconds_remaining: number;
}

const PAIRING_KEY = ["pairing"] as const;
// Les demandes expirent toutes seules. Sans relecture régulière, l'humain verrait une
// demande morte et lirait son refus comme une panne (critère 6 du ticket ce66f5bb).
const REQUESTS_REFRESH_MS = 5000;
// Repli quand le serveur n'a pas dit ce qu'il restait de la fenêtre : une valeur courte,
// parce qu'un code périmé affiché est pire qu'un appel de plus.
const CODE_FALLBACK_MS = 5000;

export function usePairingRequests() {
  return useQuery({
    queryKey: [...PAIRING_KEY, "requests"],
    queryFn: ({ signal }) => request<PairingRequest[]>("/api/pairing/requests", { signal }),
    refetchInterval: REQUESTS_REFRESH_MS,
  });
}

export function usePairedEnvironments() {
  return useQuery({
    queryKey: [...PAIRING_KEY, "peers"],
    queryFn: ({ signal }) => request<PairedEnvironment[]>("/api/pairing/peers", { signal }),
    refetchInterval: REQUESTS_REFRESH_MS,
  });
}

/**
 * Le code d'une demande, relu quand sa fenêtre tourne.
 *
 * L'intervalle vient de ce que le SERVEUR dit qu'il reste, et non d'un compte local : les
 * deux horloges n'ont aucune raison de s'accorder, et c'est celle du serveur qui décide
 * si le code est accepté.
 */
export function usePairingCode(baseUrl: string | null) {
  return useQuery({
    enabled: baseUrl !== null,
    queryKey: [...PAIRING_KEY, "code", baseUrl],
    queryFn: ({ signal }) =>
      request<PairingCode>(
        `/api/pairing/code?base_url=${encodeURIComponent(baseUrl ?? "")}`,
        { signal },
      ),
    // Jamais servi d'un cache : un code périmé qui s'affiche se lit comme un code valide.
    gcTime: 0,
    staleTime: 0,
    refetchInterval: (query) => {
      const reste = query.state.data?.seconds_remaining;
      return reste === undefined ? CODE_FALLBACK_MS : Math.max(reste, 1) * 1000;
    },
  });
}

export function useRejectRequest() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (baseUrl: string) =>
      // `undefined` et non `void` : la route rend 204, donc pas de corps — et `void` n'est
      // pas un type de valeur, seulement un type de retour.
      request<undefined>(`/api/pairing/requests?base_url=${encodeURIComponent(baseUrl)}`, {
        method: "DELETE",
      }),
    // Les deux listes se relisent au serveur : lui seul sait ce qui reste.
    onSettled: () => client.invalidateQueries({ queryKey: PAIRING_KEY }),
  });
}

/**
 * La clef de libellé d'un refus d'appariement, choisie sur ce que le serveur a RÉELLEMENT dit.
 *
 * Chaque refus appelle un geste différent — désigner, en choisir un autre, révoquer,
 * rafraîchir la liste —, et c'est pour cela qu'ils ne se fondent pas en « une erreur est
 * survenue » : un message unique fait chercher la panne là où elle n'est pas.
 */
export function designationRefusKey(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "pairing.designation.errors.unexpected";
  }
  if (error.status === 409) {
    if (error.detail === "appariement_conclu") {
      return "pairing.designation.errors.settled";
    }
    return "pairing.designation.errors.taken";
  }
  if (error.status === 404) {
    // L'environnement vient d'être supprimé ailleurs, ou la demande d'expirer : deux
    // disparitions, et la liste relue dira laquelle.
    return error.detail === "environnement_absent"
      ? "pairing.designation.errors.environmentGone"
      : "pairing.designation.errors.requestGone";
  }
  return "pairing.designation.errors.unexpected";
}

/** Désigne l'environnement d'une demande en attente. Libre tant qu'elle l'est. */
export function useDesignateRequestEnvironment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ baseUrl, environmentId }: { baseUrl: string; environmentId: string }) =>
      request<PairingRequest>(
        `/api/pairing/requests/environment?base_url=${encodeURIComponent(baseUrl)}`,
        { method: "PUT", body: JSON.stringify({ environment_id: environmentId }) },
      ),
    // Le référentiel aussi : un environnement désigné n'est plus supprimable, et sa
    // ligne doit le dire sans qu'on change d'écran puis revienne.
    onSettled: () => {
      void client.invalidateQueries({ queryKey: PAIRING_KEY });
      void client.invalidateQueries({ queryKey: ["environments"] });
    },
  });
}

/** Rattache un appariement HÉRITÉ, conclu avant que la désignation n'existe. */
export function useAttachPeerEnvironment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ baseUrl, environmentId }: { baseUrl: string; environmentId: string }) =>
      request<PairedEnvironment>(
        `/api/pairing/peers/environment?base_url=${encodeURIComponent(baseUrl)}`,
        { method: "PUT", body: JSON.stringify({ environment_id: environmentId }) },
      ),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: PAIRING_KEY });
      void client.invalidateQueries({ queryKey: ["environments"] });
    },
  });
}

/**
 * Révoque un appariement conclu : sa clé est DÉTRUITE côté module d'enrôlement.
 *
 * Le référentiel est réinvalidé en même temps : l'environnement quitté redevient
 * supprimable et réappariable, et sa ligne doit le dire sans qu'on change d'écran puis
 * revienne. La révocation porte sur l'appariement, pas sur l'environnement — qui reste
 * au référentiel.
 */
export function useRevokePeer() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (baseUrl: string) =>
      request<undefined>(`/api/pairing/peers?base_url=${encodeURIComponent(baseUrl)}`, {
        method: "DELETE",
      }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: PAIRING_KEY });
      void client.invalidateQueries({ queryKey: ["environments"] });
    },
  });
}


/**
 * Change l'adresse où l'on joint une stack appariée. Son identité ne change pas.
 *
 * C'est la seule chose que ce module compose vers l'extérieur — l'avis de révocation —,
 * et c'est pour cela qu'elle se saisit ici plutôt que d'être déclarée par la stack.
 */
export function useSetPeerContactUrl() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ baseUrl, contactUrl }: { baseUrl: string; contactUrl: string }) =>
      request<PairedEnvironment>(
        `/api/pairing/peers/contact?base_url=${encodeURIComponent(baseUrl)}`,
        { method: "PUT", body: JSON.stringify({ contact_url: contactUrl }) },
      ),
    onSettled: () => client.invalidateQueries({ queryKey: PAIRING_KEY }),
  });
}
