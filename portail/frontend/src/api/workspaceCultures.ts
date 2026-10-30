import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@miles/socle-web";

/**
 * Cultures du PARAMÉTRAGE d'un workspace, et non celles de l'application : les langues
 * dans lesquelles on traduit ce que ce workspace décrit. Deux workspaces du même Miles
 * peuvent viser des pays différents, et un exploitant qui lit le back-office en français
 * traduit un paramétrage en arabe. Les cultures de l'outil sont dans `@miles/socle-web`.
 */
export interface WorkspaceCultures {
  default: string;
  /** Par code ; la culture par défaut est à part et vient toujours en premier. */
  additional: string[];
}

const KEY = ["workspace-cultures"] as const;

function keyOf(id: string) {
  return [...KEY, id] as const;
}

function path(id: string, tail = "") {
  return `/api/workspaces/${encodeURIComponent(id)}/cultures${tail}`;
}

export function useWorkspaceCultures(id: string) {
  return useQuery({
    queryKey: keyOf(id),
    queryFn: ({ signal }) => request<WorkspaceCultures>(path(id), { signal }),
  });
}

/** La culture par défaut d'abord, puis les additionnelles : l'ordre de tous les écrans. */
export function orderedCultures(cultures: WorkspaceCultures | undefined): string[] {
  return cultures ? [cultures.default, ...cultures.additional] : [];
}

export function useAddWorkspaceCulture(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (culture: string) =>
      request<WorkspaceCultures>(path(id), {
        method: "POST",
        body: JSON.stringify({ culture }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: keyOf(id) }),
  });
}

/** Retire une culture additionnelle ; ses fichiers restent dans le dépôt. */
export function useRemoveWorkspaceCulture(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (culture: string) =>
      request<WorkspaceCultures>(path(id, `/${encodeURIComponent(culture)}`), {
        method: "DELETE",
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: keyOf(id) }),
  });
}

export function useSetDefaultWorkspaceCulture(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (culture: string) =>
      request<WorkspaceCultures>(path(id, "/default"), {
        method: "PUT",
        body: JSON.stringify({ culture }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: keyOf(id) }),
  });
}
