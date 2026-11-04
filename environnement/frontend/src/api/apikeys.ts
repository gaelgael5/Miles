import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@miles/socle-web";

/**
 * Les clés d'API d'ingestion de cette stack.
 *
 * Décision de Gael du 02/11/2026 : « l'environnement porte une page pour gérer les clés
 * d'api », « une cle ouvre les portes qu'on lui octroie ». Chaque environnement
 * authentifie seul les systèmes tiers qui déposent chez lui — aucune de ces lectures ne
 * passe par le portail, et une stack reste alimentable s'il est arrêté.
 */
export interface ApiKey {
  id: string;
  label: string;
  /** Le début de la clé. Il sert à reconnaître une ligne, jamais à appeler. */
  prefix: string;
  sources: string[];
  /**
   * Les octrois que la version servie ne déclare plus. Relus à chaque lecture : l'octroi
   * désigne un objet de la version, et une version suivante peut l'avoir retiré.
   */
  missing_sources: string[];
  created_at: string;
  created_by: string;
  revoked_at: string | null;
  last_used_at: string | null;
}

/** Ce que la création rend, et cette fois seulement : le serveur n'en garde que l'empreinte. */
export interface IssuedKey {
  key: ApiKey;
  secret: string;
}

const KEYS = ["api-keys"] as const;

export function useApiKeys() {
  return useQuery({
    queryKey: KEYS,
    queryFn: ({ signal }) => request<ApiKey[]>("/api/api-keys", { signal }),
  });
}

/**
 * Les sources que la version servie déclare : les seuls octrois possibles.
 *
 * L'écran ne propose que ça. Un champ libre ferait découvrir le refus après la saisie,
 * alors qu'on peut n'offrir que ce qui marche — la même règle que les filtres d'un
 * storage, et que l'arbre des propriétés du portail.
 */
export function useDeclaredSources() {
  return useQuery({
    queryKey: [...KEYS, "sources"],
    queryFn: ({ signal }) =>
      request<{ sources: string[] }>("/api/api-keys/sources", { signal }),
  });
}

function useKeyMutation<I, O>(mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    // La liste se relit au serveur : il est seul à savoir ce qui a été enregistré, et
    // seul à savoir quels octrois la version servie déclare encore.
    onSuccess: () => client.invalidateQueries({ queryKey: KEYS }),
  });
}

export function useIssueKey() {
  return useKeyMutation(({ label, sources }: { label: string; sources: string[] }) =>
    request<IssuedKey>("/api/api-keys", {
      method: "POST",
      body: JSON.stringify({ label, sources }),
    }),
  );
}

export function useSetGrants() {
  return useKeyMutation(({ id, sources }: { id: string; sources: string[] }) =>
    request<ApiKey>(`/api/api-keys/${encodeURIComponent(id)}/grants`, {
      method: "PUT",
      body: JSON.stringify({ sources }),
    }),
  );
}

export function useRevokeKey() {
  return useKeyMutation((id: string) =>
    request<ApiKey>(`/api/api-keys/${encodeURIComponent(id)}/revoke`, { method: "POST" }),
  );
}
