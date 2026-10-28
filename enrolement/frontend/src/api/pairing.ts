import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@miles/socle-web";

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
