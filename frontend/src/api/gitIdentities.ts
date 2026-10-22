import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

export interface RepositoryCheck {
  workspace_id: string;
  workspace_name: string;
  /** null : la forge n'a pas répondu à la vérification. */
  can_write: boolean | null;
}

/** Identité git de la personne pour une connexion : jamais le jeton lui-même. */
export interface GitIdentity {
  connection_id: string;
  connection_label: string;
  base_url: string;
  registered: boolean;
  account: {
    login: string;
    name: string;
    email: string;
    /** « noreply » : repli visible quand le compte n'expose aucun e-mail lisible. */
    email_origin: "public" | "emails" | "noreply";
  } | null;
  repositories: RepositoryCheck[];
  verified_at: string | null;
}

const ROUTE = "/api/auth/me/git-identities";
const KEY = ["git-identities"] as const;

export function useGitIdentities() {
  return useQuery({
    queryKey: KEY,
    queryFn: ({ signal }) => request<GitIdentity[]>(ROUTE, { signal }),
  });
}

export function useRegisterGitIdentity(connectionId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (token: string) =>
      request<GitIdentity>(`${ROUTE}/${encodeURIComponent(connectionId)}`, {
        method: "PUT",
        body: JSON.stringify({ token }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  });
}

export function useRemoveGitIdentity(connectionId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<undefined>(`${ROUTE}/${encodeURIComponent(connectionId)}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  });
}
