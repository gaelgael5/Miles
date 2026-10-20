import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, request } from "./http";

export { ApiError };

export interface BootstrapStatus {
  admin_declared: boolean;
}

export interface Me {
  kind: "local_admin" | "oidc";
  username: string;
  email: string | null;
  /** Connecteur OIDC de la session ; null pour le compte d'amorçage. */
  directory: string | null;
  /** Compte d'amorçage, ou session OIDC reconnue administrateur par son e-mail. */
  root_admin: boolean;
}

export interface BootstrapInput {
  email: string;
  username: string;
  password: string;
}

export interface LoginInput {
  username: string;
  password: string;
}

const ME_KEY = ["auth", "me"] as const;
const STATUS_KEY = ["auth", "bootstrap-status"] as const;

export function fetchBootstrapStatus(signal?: AbortSignal) {
  return request<BootstrapStatus>("/api/bootstrap/status", { signal });
}

export async function fetchMe(signal?: AbortSignal): Promise<Me | null> {
  try {
    return await request<Me>("/api/auth/me", { signal });
  } catch (error) {
    // 401 n'est pas une panne : c'est « pas connecté », et l'écran de connexion s'affiche.
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }
    throw error;
  }
}

export function useBootstrapStatus() {
  return useQuery({ queryKey: STATUS_KEY, queryFn: ({ signal }) => fetchBootstrapStatus(signal) });
}

export function useMe(enabled: boolean) {
  return useQuery({ queryKey: ME_KEY, queryFn: ({ signal }) => fetchMe(signal), enabled });
}

function useAuthMutation<I>(mutationFn: (input: I) => Promise<unknown>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    // La source de vérité reste le serveur : on relit l'état au lieu de le déduire.
    onSuccess: () => client.invalidateQueries({ queryKey: ["auth"] }),
  });
}

export function useBootstrap() {
  return useAuthMutation((input: BootstrapInput) =>
    request<Me>("/api/bootstrap", { method: "POST", body: JSON.stringify(input) }),
  );
}

export function useLogin() {
  return useAuthMutation((input: LoginInput) =>
    request<Me>("/api/auth/login", { method: "POST", body: JSON.stringify(input) }),
  );
}

export function useLogout() {
  return useAuthMutation(() => request<undefined>("/api/auth/logout", { method: "POST" }));
}
