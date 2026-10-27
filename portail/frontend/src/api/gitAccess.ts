import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@miles/socle-web";


/** Une forge ou une organisation, et son PAT. */
export interface GitConnection {
  id: string;
  label: string;
  base_url: string;
  token_secret_slug: string;
  workspaces: string[];
  created_at: string;
  updated_at: string;
}

export interface ConnectionInput {
  label: string;
  base_url: string;
  token_secret_slug: string;
}

const CONNECTIONS = ["git-connections"] as const;
// Un changement d'accès réécrit le dernier essai des workspaces concernés.
const WORKSPACES = ["workspaces"] as const;

function path(root: string, id?: string) {
  return id === undefined ? root : `${root}/${encodeURIComponent(id)}`;
}

function useInvalidating<I, O>(mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: async () => {
      await Promise.all(
        [CONNECTIONS, WORKSPACES].map((queryKey) => client.invalidateQueries({ queryKey })),
      );
    },
  });
}

export function useConnections() {
  return useQuery({
    queryKey: CONNECTIONS,
    queryFn: ({ signal }) => request<GitConnection[]>("/api/git-connections", { signal }),
  });
}

export function useCreateConnection() {
  return useInvalidating((input: ConnectionInput & { id: string }) =>
    request<GitConnection>("/api/git-connections", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
}

export function useUpdateConnection(id: string) {
  return useInvalidating((input: ConnectionInput & { verification_suffix: string }) =>
    request<GitConnection>(path("/api/git-connections", id), {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  );
}

export function useDeleteConnection() {
  return useInvalidating((id: string) =>
    request<undefined>(path("/api/git-connections", id), { method: "DELETE" }),
  );
}
