import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

/** Branche de travail d'un workspace : la base, ou une branche fille tirée d'elle. */
export interface WorkBranch {
  /** Figé à la création ; c'est lui qu'affiche le menu. */
  slug: string;
  label: string;
  /** Nom git : `back/<workspace>/<slug>`. */
  branch: string;
  base: boolean;
}

function root(workspaceId: string) {
  return `/api/workspaces/${encodeURIComponent(workspaceId)}/branches`;
}

function key(workspaceId: string) {
  return ["branches", workspaceId] as const;
}

export function useBranches(workspaceId: string, enabled = true) {
  return useQuery({
    queryKey: key(workspaceId),
    enabled,
    queryFn: ({ signal }) => request<WorkBranch[]>(root(workspaceId), { signal }),
  });
}

export function useCreateBranch(workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { label: string; slug: string }) =>
      request<WorkBranch>(root(workspaceId), { method: "POST", body: JSON.stringify(input) }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(workspaceId) }),
  });
}

const VIEWS_KEY = ["branch-views"] as const;

/** Branche que la personne connectée regarde, par workspace ; absente : la base. */
export function useBranchViews() {
  return useQuery({
    queryKey: VIEWS_KEY,
    queryFn: ({ signal }) => request<Record<string, string>>("/api/branch-views", { signal }),
  });
}

/** Change la branche regardée : retenue côté serveur, pour ce compte seulement. */
export function useSetBranchView(workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (branch: string) =>
      request<WorkBranch>(`${root(workspaceId)}/view`, {
        method: "PUT",
        body: JSON.stringify({ branch }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: VIEWS_KEY }),
  });
}
