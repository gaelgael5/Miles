import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@miles/socle-web";


export type Outcome = "ok" | "realm_inconnu" | "injoignable" | "refuse";

/** Le secret n'y figure que par le slug du secret qui le porte. */
export interface SecurityService {
  id: string;
  kind: string;
  base_url: string;
  realm: string;
  client_id: string;
  client_secret_slug: string;
  last_check_outcome: Outcome | null;
  last_check_at: string | null;
  dependent_installations: number;
}

export interface SecurityInput {
  base_url: string;
  realm: string;
  client_id: string;
  client_secret_slug: string;
}

const KEY = ["security-services"] as const;
const ROUTE = "/api/security-services";

export function useSecurityServices() {
  return useQuery({
    queryKey: KEY,
    queryFn: ({ signal }) => request<SecurityService[]>(ROUTE, { signal }),
  });
}

function useSecurityMutation<I>(mutationFn: (input: I) => Promise<SecurityService>) {
  const client = useQueryClient();
  return useMutation({ mutationFn, onSuccess: () => client.invalidateQueries({ queryKey: KEY }) });
}

export function useDeclareSecurityService() {
  return useSecurityMutation((input: SecurityInput & { id: string }) =>
    request<SecurityService>(ROUTE, { method: "POST", body: JSON.stringify(input) }),
  );
}

export function useUpdateSecurityService(id: string) {
  return useSecurityMutation((input: SecurityInput) =>
    request<SecurityService>(`${ROUTE}/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  );
}

export function useVerifySecurityService(id: string) {
  return useSecurityMutation(() =>
    request<SecurityService>(`${ROUTE}/${encodeURIComponent(id)}/verification`, {
      method: "POST",
    }),
  );
}
