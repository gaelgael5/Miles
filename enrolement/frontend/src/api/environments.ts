import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, request } from "@miles/socle-web";

/** Un environnement du référentiel : ce qui se lit, ce qui s'écrit, et son appariement. */
export interface Environment {
  /**
   * L'identifiant STABLE. C'est lui qu'on renvoie pour renommer ou supprimer : le slug
   * est renommable, s'en servir de clé ferait échouer l'action juste après un renommage.
   */
  id: string;
  slug: string;
  label: string;
  created_at: string;
  updated_at: string;
  /**
   * L'origine de la stack appariée à cet environnement, nulle tant qu'aucune ne l'est.
   * Nul n'est pas une anomalie : un environnement déclaré et pas encore apparié est
   * l'état normal du premier jour.
   */
  paired_base_url: string | null;
  /**
   * L'origine d'une demande d'appariement EN ATTENTE qui l'a désigné. Elle ne le consomme
   * pas — refusée ou expirée, elle le libère — mais elle retient sa suppression.
   */
  designated_base_url: string | null;
}

export interface EnvironmentInput {
  label: string;
  slug: string;
}

const ENVIRONMENTS_KEY = ["environments"] as const;
// La même borne que le serveur et que la base. Tronquer ici évite de proposer un slug
// que l'API refusera, sans jamais réécrire ce que l'utilisateur a tapé lui-même.
const MAX_SLUG_LENGTH = 48;

/**
 * Le slug proposé depuis le libellé — une AIDE À LA SAISIE, pas une normalisation.
 *
 * Elle vit ici, et pas au serveur, parce que ce qu'elle produit est modifiable : le
 * serveur reçoit un choix, qu'il valide sans jamais le réécrire. Si la dérivation ne
 * donne rien d'utilisable — ponctuation seule, écriture sans translittération latine —
 * elle rend la chaîne vide et l'écran demande un slug. Elle n'en invente jamais un :
 * un slug que personne n'a choisi est un slug que personne ne reconnaît, et il finirait
 * recopié dans une procédure.
 */
export function slugFromLabel(label: string): string {
  return label
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .slice(0, MAX_SLUG_LENGTH)
    .replace(/^-+|-+$/g, "");
}

/** La clef de libellé d'un refus, choisie sur ce que le serveur a RÉELLEMENT dit. */
export function refusKey(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "environments.errors.unexpected";
  }
  if (error.status === 422) {
    return error.detail === "label" ? "environments.errors.label" : "environments.errors.slug";
  }
  if (error.status === 409) {
    // Trois refus de même code, trois gestes différents : corriger un slug pris,
    // révoquer un appariement, ou refuser la demande qui le désigne. Les fondre ferait
    // chercher une révocation là où il n'y a qu'une liste déroulante à changer.
    if (error.detail === "environnement_apparie") {
      return "environments.errors.paired";
    }
    if (error.detail === "environnement_designe") {
      return "environments.errors.designated";
    }
    return "environments.errors.slugTaken";
  }
  if (error.status === 404) {
    return "environments.errors.absent";
  }
  return "environments.errors.unexpected";
}

export function useEnvironments() {
  return useQuery({
    queryKey: ENVIRONMENTS_KEY,
    queryFn: ({ signal }) => request<Environment[]>("/api/environments", { signal }),
  });
}

export function useCreateEnvironment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: EnvironmentInput) =>
      request<Environment>("/api/environments", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ENVIRONMENTS_KEY }),
  });
}

export function useRenameEnvironment() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...input }: EnvironmentInput & { id: string }) =>
      request<Environment>(`/api/environments/${encodeURIComponent(id)}`, {
        method: "PUT",
        body: JSON.stringify(input),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ENVIRONMENTS_KEY }),
  });
}

export function useDeleteEnvironment() {
  const client = useQueryClient();
  return useMutation({
    // `undefined` et non `void` : la route rend 204, donc pas de corps — et `void` n'est
    // pas un type de valeur, seulement un type de retour.
    mutationFn: (id: string) =>
      request<undefined>(`/api/environments/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSettled: () => client.invalidateQueries({ queryKey: ENVIRONMENTS_KEY }),
  });
}
