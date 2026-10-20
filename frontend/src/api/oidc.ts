import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

/** Ce que l'écran de connexion voit d'un connecteur actif. */
export interface PublicConnector {
  id: string;
  label: string;
}

/** Fiche d'administration : le secret client n'y figure que par son slug. */
export interface Connector {
  id: string;
  label: string;
  issuer: string;
  client_id: string;
  client_secret_slug: string;
  scopes: string;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export type ConnectorInput = Omit<Connector, "created_at" | "updated_at">;

export const DEFAULT_SCOPES = "openid email profile";
const CONNECTORS_KEY = ["oidc", "connectors"] as const;

/** Adresse de départ : une navigation complète, le navigateur part chez le fournisseur. */
export function startLoginUrl(connectorId: string): string {
  return `/api/auth/oidc/start?connector=${encodeURIComponent(connectorId)}`;
}

export function usePublicConnectors() {
  return useQuery({
    queryKey: ["oidc", "public"],
    queryFn: ({ signal }) => request<PublicConnector[]>("/api/auth/oidc/connectors", { signal }),
  });
}

export function useConnectors() {
  return useQuery({
    queryKey: CONNECTORS_KEY,
    queryFn: ({ signal }) => request<Connector[]>("/api/oidc/connectors", { signal }),
  });
}

function useConnectorMutation<I, O>(mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => client.invalidateQueries({ queryKey: ["oidc"] }),
  });
}

export function useSaveConnector(existing: boolean) {
  return useConnectorMutation(({ id, ...body }: ConnectorInput) =>
    existing
      ? request<Connector>(`/api/oidc/connectors/${encodeURIComponent(id)}`, {
          method: "PUT",
          body: JSON.stringify(body),
        })
      : request<Connector>("/api/oidc/connectors", {
          method: "POST",
          body: JSON.stringify({ id, ...body }),
        }),
  );
}

export function useDeleteConnector() {
  return useConnectorMutation((id: string) =>
    request<undefined>(`/api/oidc/connectors/${encodeURIComponent(id)}`, { method: "DELETE" }),
  );
}
