import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, request } from "@miles/socle-web";

/** Une version publiée du workspace, telle que son dépôt la porte. */
export interface PublishedVersion {
  number: number;
  label: string;
  commit: string;
  author: string;
  saved_at: string;
  /** Nulle pour une étiquette d'avant les branches filles : l'écran le dit. */
  branch: string | null;
}

/**
 * Ce qui est ordonné à l'environnement, et l'INSTANTANÉ de sa dernière réponse.
 *
 * `served_commit`, `refusal` et `acked_at` décrivent le dernier échange, pas l'état
 * courant du pair : il peut avoir redémarré, perdu son disque ou fini d'appliquer depuis.
 * C'est pour cela qu'ils vont toujours avec leur date, et que l'écran dit « au
 * <instant> » plutôt qu'« actuellement ».
 */
export interface OrderedVersion {
  number: number;
  commit: string;
  ordered_at: string;
  served_commit: string | null;
  refusal: string | null;
  acked_at: string | null;
  /** Calculé par le serveur : la comparaison refaite ici la ferait un jour autrement. */
  up_to_date: boolean;
}

const VERSIONS_KEY = "versions";
const ORDERED_KEY = "ordered-version";

/**
 * La clef de libellé d'un refus, choisie sur ce que le serveur a RÉELLEMENT dit.
 *
 * Cinq refus distincts, et c'est délibéré : placer un workspace, réapparier le module de
 * paramétrage, configurer un dépôt, rechoisir une version, ou regarder du côté de la
 * forge. Un message unique les enverrait tous chercher au même endroit.
 */
export function hostingRefusKey(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "workspaces.version.errors.unexpected";
  }
  if (error.status === 409) {
    const connus: Record<string, string> = {
      aucun_workspace_place: "workspaces.version.errors.noWorkspace",
      workspace_non_confie: "workspaces.version.errors.notConfided",
      depot_non_configure: "workspaces.version.errors.noRepo",
    };
    return connus[String(error.detail)] ?? "workspaces.version.errors.unexpected";
  }
  if (error.status === 404) {
    return "workspaces.version.errors.unknownVersion";
  }
  if (error.status === 422) {
    const detail = error.detail as { code?: string } | null;
    if (detail !== null && typeof detail === "object" && detail.code === "depot_illisible") {
      return "workspaces.version.errors.repository";
    }
  }
  return "workspaces.version.errors.unexpected";
}

/**
 * Ce que git a dit quand le dépôt n'a pas pu être lu, pour que l'écran le NOMME.
 *
 * « identifiants », « dépôt inexistant » et « injoignable » n'appellent pas le même
 * geste, et c'est la seule information qui permette de choisir lequel.
 */
export function repositoryReason(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 422) {
    return null;
  }
  const detail = error.detail as { code?: string; reason?: string } | null;
  if (detail === null || typeof detail !== "object" || detail.code !== "depot_illisible") {
    return null;
  }
  return detail.reason ?? null;
}

export function usePublishedVersions(environmentId: string) {
  return useQuery({
    queryKey: [VERSIONS_KEY, environmentId],
    // Chaque affichage relit le dépôt : une liste servie d'un cache ferait choisir une
    // version supprimée depuis. Le miroir git du serveur est déjà le cache, et il ne
    // récupère que ce qui a changé.
    queryFn: ({ signal }) =>
      request<PublishedVersion[]>(
        `/api/environments/${encodeURIComponent(environmentId)}/versions`,
        { signal },
      ),
    retry: false,
  });
}

export function useOrderedVersion(environmentId: string) {
  return useQuery({
    queryKey: [ORDERED_KEY, environmentId],
    queryFn: ({ signal }) =>
      request<OrderedVersion>(`/api/environments/${encodeURIComponent(environmentId)}/version`, {
        signal,
      }),
    // 404 veut dire « aucune version ordonnée », qui est un état et non une panne :
    // réessayer ne changerait rien, et ferait clignoter l'écran.
    retry: false,
  });
}

export function useOrderVersion(environmentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (number: number) =>
      request<OrderedVersion>(`/api/environments/${encodeURIComponent(environmentId)}/version`, {
        method: "PUT",
        body: JSON.stringify({ number }),
      }),
    onSuccess: (ordonnee) => client.setQueryData([ORDERED_KEY, environmentId], ordonnee),
  });
}

/**
 * Repousse l'ordre déjà enregistré, sans le changer.
 *
 * Le geste de réparation : un environnement redémarré ou dont le volume est neuf ne sait
 * pas qu'une version lui est ordonnée, et n'a aucun moyen de l'apprendre seul — c'est le
 * sens choisi pour ces deux routes.
 */
export function useResendOrder(environmentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<OrderedVersion>(
        `/api/environments/${encodeURIComponent(environmentId)}/version/resend`,
        { method: "POST" },
      ),
    onSuccess: (ordonnee) => client.setQueryData([ORDERED_KEY, environmentId], ordonnee),
  });
}
