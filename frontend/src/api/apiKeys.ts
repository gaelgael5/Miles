import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

export type Access = "lecture" | "ecriture";

export interface Grant {
  workspace_id: string;
  access: Access;
}

/** Ce que l'API rend d'une clé : jamais la clé, que Miles ne garde pas. */
export interface ApiKey {
  id: string;
  label: string;
  /** Début de la clé, pour la reconnaître ; il ne suffit pas à l'utiliser. */
  prefix: string;
  grants: Grant[];
  created_at: string;
  created_by: string;
  revoked_at: string | null;
  last_used_at: string | null;
}

export interface IssuedKey {
  key: ApiKey;
  /** Montrée cette seule fois, à l'émission. */
  secret: string;
}

const KEY = ["api-keys"] as const;
const ROOT = "/api/api-keys";

export function useApiKeys() {
  return useQuery({
    queryKey: KEY,
    queryFn: ({ signal }) => request<ApiKey[]>(ROOT, { signal }),
  });
}

function useKeyMutation<I, O>(run: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({ mutationFn: run, onSuccess: () => client.invalidateQueries({ queryKey: KEY }) });
}

export function useIssueApiKey() {
  return useKeyMutation((input: { label: string; grants: Grant[] }) =>
    request<IssuedKey>(ROOT, { method: "POST", body: JSON.stringify(input) }),
  );
}

export function useSetApiKeyGrants(id: string) {
  return useKeyMutation((grants: Grant[]) =>
    request<ApiKey>(`${ROOT}/${encodeURIComponent(id)}/grants`, {
      method: "PUT",
      body: JSON.stringify({ grants }),
    }),
  );
}

export function useRevokeApiKey(id: string) {
  return useKeyMutation(() =>
    request<ApiKey>(`${ROOT}/${encodeURIComponent(id)}/revoke`, { method: "POST" }),
  );
}
