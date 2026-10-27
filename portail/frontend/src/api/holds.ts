import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@miles/socle-web";


/**
 * Prise de main d'une branche fille (story 9def0adc) : une personne par branche, une
 * branche par personne. Qui a la main y modifie seul, en commits locaux à son nom,
 * qu'il publie ensuite avec son propre PAT.
 */
export interface Hold {
  slug: string;
  /** Nom et login de forge de qui a la main. */
  holder: string;
  mine: boolean;
  taken_at: string;
}

export interface HoldStatus {
  hold: Hold | null;
  /** Commits locaux non publiés ; null pour qui n'a pas la main. */
  unpublished: number | null;
}

/** Travail non publié rangé sur la forge au déverrouillage (story fd1eb7da). */
export interface Shelf {
  workspace_id: string;
  workspace_name: string;
  slug: string;
  /** Branche de rangement sur la forge : `shelve/<login>/<branche>`. */
  shelf_branch: string;
  mine: boolean;
  shelved_at: string;
}

function workspacePath(workspaceId: string) {
  return `/api/workspaces/${encodeURIComponent(workspaceId)}`;
}

function holdPath(workspaceId: string, slug: string) {
  return `${workspacePath(workspaceId)}/branches/${encodeURIComponent(slug)}/hold`;
}

function holdsKey(workspaceId: string) {
  return ["holds", workspaceId] as const;
}

function statusKey(workspaceId: string, slug: string) {
  return ["hold", workspaceId, slug] as const;
}

/** Qui tient quelle branche du workspace. */
export function useHolds(workspaceId: string, enabled = true) {
  return useQuery({
    queryKey: holdsKey(workspaceId),
    enabled,
    queryFn: ({ signal }) => request<Hold[]>(`${workspacePath(workspaceId)}/holds`, { signal }),
  });
}

export function useHoldStatus(workspaceId: string, slug: string, enabled: boolean) {
  return useQuery({
    queryKey: statusKey(workspaceId, slug),
    enabled,
    queryFn: ({ signal }) => request<HoldStatus>(holdPath(workspaceId, slug), { signal }),
  });
}

/**
 * Après une prise, une publication ou un rendu, tout ce qu'on lisait de la branche est à
 * relire : la personne qui a la main lit sa propre copie, les autres ce qui est publié.
 */
function refresh(client: QueryClient, workspaceId: string, slug: string) {
  return client.invalidateQueries({
    predicate: ({ queryKey: [kind, workspace, branch] }) => {
      if (kind === "my-shelves") {
        return true;
      }
      if (kind === "holds" || kind === "shelves") {
        return workspace === workspaceId;
      }
      return workspace === workspaceId && branch === slug;
    },
  });
}

function useHoldMutation<O>(workspaceId: string, slug: string, mutationFn: () => Promise<O>) {
  const client = useQueryClient();
  return useMutation({ mutationFn, onSettled: () => refresh(client, workspaceId, slug) });
}

export function useTakeHold(workspaceId: string, slug: string) {
  return useHoldMutation(workspaceId, slug, () =>
    request<Hold>(holdPath(workspaceId, slug), { method: "POST" }),
  );
}

export function usePublishHold(workspaceId: string, slug: string) {
  return useHoldMutation(workspaceId, slug, () =>
    request<{ published: number }>(`${holdPath(workspaceId, slug)}/publish`, { method: "POST" }),
  );
}

export function useReleaseHold(workspaceId: string, slug: string) {
  return useHoldMutation(workspaceId, slug, () =>
    request<{ released: boolean }>(holdPath(workspaceId, slug), { method: "DELETE" }),
  );
}

export function useShelves(workspaceId: string, enabled = true) {
  return useQuery({
    queryKey: ["shelves", workspaceId] as const,
    enabled,
    queryFn: ({ signal }) => request<Shelf[]>(`${workspacePath(workspaceId)}/shelves`, { signal }),
  });
}

/** Mes rangements, tous workspaces confondus : le profil les montre. */
export function useMyShelves() {
  return useQuery({
    queryKey: ["my-shelves"] as const,
    queryFn: ({ signal }) => request<Shelf[]>("/api/auth/me/shelves", { signal }),
  });
}

/** Déverrouiller qui tient la branche : son travail non publié est rangé sur la forge. */
export function useUnlockHold(workspaceId: string, slug: string) {
  return useHoldMutation(workspaceId, slug, () =>
    request<{ shelf: Shelf | null }>(`${holdPath(workspaceId, slug)}/unlock`, { method: "POST" }),
  );
}
