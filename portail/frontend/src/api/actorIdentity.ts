import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

/** GUID d'acteur (story 52ac5782) : le même que dans le profil du portail, pour l'OBO. */
export interface ActorIdentity {
  /** null : aucun GUID ; les appels MCP faits en son nom restent attribués à la clé. */
  actor: string | null;
}

const ROUTE = "/api/auth/me/identity";
const KEY = ["actor-identity"] as const;

export function useActorIdentity() {
  return useQuery({
    queryKey: KEY,
    queryFn: ({ signal }) => request<ActorIdentity>(ROUTE, { signal }),
  });
}

export function useSetActorIdentity() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (actor: string) =>
      request<ActorIdentity>(ROUTE, { method: "PUT", body: JSON.stringify({ actor }) }),
    onSuccess: (saved) => client.setQueryData(KEY, saved),
  });
}

export function useRemoveActorIdentity() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<undefined>(ROUTE, { method: "DELETE" }),
    onSuccess: () => client.setQueryData(KEY, { actor: null }),
  });
}
