import { ApiError } from "@miles/socle-web";

/** Index signature : i18next attend un dictionnaire d'interpolation, pas une forme fermée. */
type Options = Record<string, string | undefined>;

/**
 * Le libellé d'un refus de saisie, et ce qu'il faut pour le dire.
 *
 * Chaque refus nomme ce qui le motive : les caractères trouvés sont invisibles, et sans
 * leurs noms la personne voit sa valeur refusée sans rien pouvoir corriger.
 */
export function tradsKeyError(error: unknown): { key: string; options: Options } {
  if (!(error instanceof ApiError)) {
    return { key: "tradsKeys.errors.unexpected", options: {} };
  }
  const detail = error.detail as
    | { code?: string; culture?: string; slug?: string; found?: string[]; path?: string; field?: string; reason?: string }
    | string
    | undefined;
  if (typeof detail === "string") {
    return { key: `tradsKeys.errors.${detail}`, options: {} };
  }
  if (detail?.code === "direction_forcee") {
    return {
      key: "tradsKeys.errors.direction_forcee",
      options: { found: (detail.found ?? []).join(", ") },
    };
  }
  if (detail?.code === "valeur_par_defaut_obligatoire") {
    return {
      key: "tradsKeys.errors.valeur_par_defaut_obligatoire",
      options: { culture: detail.culture },
    };
  }
  if (detail?.code === "culture_hors_workspace") {
    return {
      key: "tradsKeys.errors.culture_hors_workspace",
      options: { culture: detail.culture },
    };
  }
  if (detail?.code === "slug_pris" || detail?.code === "cle_inconnue") {
    return { key: `tradsKeys.errors.${detail.code}`, options: { slug: detail.slug } };
  }
  if (detail?.code === "trads_illisible") {
    return { key: "tradsKeys.errors.trads_illisible", options: { path: detail.path } };
  }
  if (detail?.code === "branche_a_bouge") {
    return { key: "tradsKeys.errors.branche_a_bouge", options: {} };
  }
  if (detail?.field === "slug") {
    return { key: "tradsKeys.errors.slug_invalide", options: {} };
  }
  return { key: "tradsKeys.errors.unexpected", options: {} };
}
