import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

export type Right = "lire" | "creer_branche" | "pousser" | "poser_tag" | "supprimer_branche";

export interface AccessReport {
  branch: string;
  tag: string;
  checks: { right: Right; ok: boolean; reason: string | null }[];
  residual_branch: string | null;
  residual_tag: string | null;
  existing_branches: number;
  initialized_branch: string | null;
  all_passed: boolean;
}

export interface Workspace {
  id: string;
  name: string;
  repo_url: string;
  git_secret_slug: string;
  security_service_id: string | null;
  last_check: AccessReport | null;
  last_check_at: string | null;
  created_at: string;
}

export interface WorkspaceInput {
  id: string;
  name: string;
  repo_url: string;
  git_secret_slug: string | null;
  security_service_id: string | null;
  verification_suffix: string;
}

const KEY = ["workspaces"] as const;

/** Suffixe tiré par l'écran : le nom de la branche s'affiche avant la fin de l'essai. */
export function newVerificationSuffix(): string {
  const bytes = new Uint8Array(4);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function verificationBranch(suffix: string): string {
  return `miles-verification-${suffix}`;
}

export function useWorkspaces() {
  return useQuery({
    queryKey: KEY,
    queryFn: ({ signal }) => request<Workspace[]>("/api/workspaces", { signal }),
  });
}

export function useCreateWorkspace() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: WorkspaceInput) =>
      request<Workspace>("/api/workspaces", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  });
}

export function useRecheckWorkspace(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (suffix: string) =>
      request<AccessReport>(`/api/workspaces/${encodeURIComponent(id)}/access-check`, {
        method: "POST",
        body: JSON.stringify({ verification_suffix: suffix }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  });
}
