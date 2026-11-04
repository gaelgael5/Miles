import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@miles/socle-web";


export interface OAuthClient {
  id: string;
  label: string;
  redirect_uris: string[];
  created_at: string;
}

/** Adresses à donner à claude.ai ; null partout si MILES_PUBLIC_URL manque. */
export interface OAuthEndpoints {
  mcp_url: string | null;
  issuer: string | null;
  authorization_endpoint: string | null;
  token_endpoint: string | null;
  suggested_redirect_uris: string[];
}

export type Access = "lecture" | "ecriture";

export interface ConsentView {
  client: { id: string; label: string };
  redirect_uri: string;
  /** Ce que la personne peut déléguer : ses propres droits, workspace par workspace. */
  allowed: { workspace_id: string; name: string; access: Access }[];
}

export interface OAuthGrant {
  id: string;
  client: string;
  grants: Record<string, Access>;
  created_at: string;
  last_used_at: string | null;
}

const CLIENTS = ["oauth-clients"] as const;
const GRANTS = ["oauth-grants"] as const;

export function useOAuthClients() {
  return useQuery({ queryKey: CLIENTS, queryFn: ({ signal }) => request<OAuthClient[]>("/api/oauth-clients", { signal }) });
}

export function useOAuthEndpoints() {
  return useQuery({
    queryKey: [...CLIENTS, "endpoints"],
    queryFn: ({ signal }) => request<OAuthEndpoints>("/api/oauth-clients/endpoints", { signal }),
  });
}

export function useDeclareOAuthClient() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { label: string; redirect_uris: string[] }) =>
      request<OAuthClient>("/api/oauth-clients", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: () => client.invalidateQueries({ queryKey: CLIENTS }),
  });
}

export function useDeleteOAuthClient(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<undefined>(`/api/oauth-clients/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: CLIENTS }),
  });
}

/** Lecture de la demande d'autorisation : ce que montre l'écran, ou un renvoi au client. */
export function useConsentView(params: Record<string, string>) {
  return useQuery({
    queryKey: ["oauth-consent", params],
    retry: false,
    queryFn: ({ signal }) =>
      request<ConsentView | { redirect: string }>("/api/oauth/authorize/check", {
        method: "POST",
        body: JSON.stringify(params),
        signal,
      }),
  });
}

export function useDecide() {
  return useMutation({
    mutationFn: (input: {
      params: Record<string, string>;
      decision: "approve" | "deny";
      grants: { workspace_id: string; access: Access }[];
    }) => request<{ redirect: string }>("/api/oauth/authorize", { method: "POST", body: JSON.stringify(input) }),
  });
}

export function useOAuthGrants() {
  return useQuery({ queryKey: GRANTS, queryFn: ({ signal }) => request<OAuthGrant[]>("/api/auth/me/oauth-grants", { signal }) });
}

export function useRevokeOAuthGrant() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      request<undefined>(`/api/auth/me/oauth-grants/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: GRANTS }),
  });
}
