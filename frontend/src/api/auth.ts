import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export interface BootstrapStatus {
  admin_declared: boolean;
}

export interface Me {
  kind: "local_admin";
  username: string;
  email: string;
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

/** Erreur HTTP de l'API, avec le `detail` qu'elle renvoie pour que l'écran dise pourquoi. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(`HTTP ${status}`);
  }
}

const ME_KEY = ["auth", "me"] as const;
const STATUS_KEY = ["auth", "bootstrap-status"] as const;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new ApiError(response.status, body.detail);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

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
