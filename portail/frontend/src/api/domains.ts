import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "@miles/socle-web";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/** Un domaine : un répertoire `domains/<name>/` de la branche (story 7fa00f56). */
export interface Domain {
  name: string;
}

// Même règle que le serveur, qui reste l'arbitre : ici, elle sert à refuser en direct.
export const DOMAIN_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,62}$/;

function key(target: WorkTarget) {
  return branchKey("domains", target);
}

export function useDomains(target: WorkTarget) {
  return useQuery({
    queryKey: key(target),
    queryFn: ({ signal }) => request<Domain[]>(atBranch(target, "domains"), { signal }),
  });
}

export function useAddDomain(target: WorkTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      request<Domain>(atBranch(target, "domains"), {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}
