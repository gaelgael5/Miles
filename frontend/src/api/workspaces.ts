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
  /** Absents tant que le dépôt n'est pas paramétré : un workspace se crée par son seul nom. */
  repo_url: string | null;
  git_connection_id: string | null;
  security_service_id: string | null;
  last_check: AccessReport | null;
  last_check_at: string | null;
  created_at: string;
  /** Aucune à la création : elle s'ouvre quand on commence à travailler. */
  work_branch: string | null;
}

export interface TreeDiagnosis {
  code: "arborescence_non_conforme";
  unexpected: string[];
  environment_dirs: string[];
  manifest: "absent" | "invalide" | "valide";
}

export interface RepositoryInput {
  git_connection_id: string;
  repo_url: string;
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
    mutationFn: (input: { id: string; name: string }) =>
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

/** Les deux « reprise_* » disent que la branche préexistait au dépôt ; « reprise » seule
 * dit qu'on n'y a rien écrit. */
export type WorkBranchOutcome = "initialisee" | "conforme" | "reprise" | "reprise_initialisee";

export function useOpenWorkBranch(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ name, adoptExisting = false }: { name: string; adoptExisting?: boolean }) =>
      request<{ workspace: Workspace; outcome: WorkBranchOutcome | null }>(
        `/api/workspaces/${encodeURIComponent(id)}/work-branch`,
        { method: "POST", body: JSON.stringify({ name, adopt_existing: adoptExisting }) },
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  });
}

/** Miles oublie le workspace ; le dépôt git et ses branches ne sont jamais touchés. */
export function useDeleteWorkspace() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      request<undefined>(`/api/workspaces/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  });
}

function workspacePath(id: string, tail: string) {
  return `/api/workspaces/${encodeURIComponent(id)}/${tail}`;
}

export function useSetRepository(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: RepositoryInput) =>
      request<Workspace>(workspacePath(id, "repository"), {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    // La connexion compte désormais ce workspace parmi ses utilisateurs.
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: KEY });
      await client.invalidateQueries({ queryKey: ["git-connections"] });
    },
  });
}

export function useSetSecurityService(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (serviceId: string | null) =>
      request<Workspace>(workspacePath(id, "security-service"), {
        method: "PUT",
        body: JSON.stringify({ security_service_id: serviceId }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: KEY }),
  });
}

/** Jours restants avant l'échéance ; négatif si elle est passée. */
export function daysUntil(isoDate: string, now: Date = new Date()): number {
  return Math.floor((new Date(isoDate).getTime() - now.getTime()) / 86_400_000);
}
