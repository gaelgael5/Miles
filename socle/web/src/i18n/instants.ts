import { useTranslation } from "react-i18next";

/**
 * Formate un instant ISO dans la culture de l'INTERFACE.
 *
 * Point UNIQUE de formatage des dates des trois produits, et c'est toute la raison d'être
 * de ce module : `toLocaleString(i18n.language)` sans argument emploie la langue du NAVIGATEUR, qui n'a
 * aucun rapport avec la culture choisie dans Miles. Le 2 novembre 2026 s'affichait
 * « 11/2/2026 » sur une interface française — illisible du 13 au 31 du mois, et lisible
 * mais FAUX du 1er au 12 (bug 4f53012d, relevé en recette le 02/11/2026).
 *
 * Un hook et non une fonction libre : la culture doit être lue PENDANT le rendu, par le
 * même abonnement i18next que les libellés. Une fonction qui lirait `i18n.language` au
 * chargement du module ne provoquerait aucun rendu au changement de langue, et les dates
 * resteraient dans l'ancienne culture jusqu'au prochain rendu venu d'ailleurs.
 *
 * La valeur nulle n'est PAS traitée ici : « jamais utilisée », « non révoquée » et « rien
 * déposé » ne se disent pas de la même façon, et un repli muet rendu par le formateur
 * ferait disparaître cette nuance de l'écran.
 */
export function useInstant(): (value: string) => string {
  const { i18n } = useTranslation();
  // SEUL appel toléré du dépôt : la règle `no-restricted-syntax` des quatre
  // configurations eslint interdit tous les autres, pour que le défaut ne puisse pas
  // revenir écran par écran — c'était déjà le cas de six écrans sur trois produits.
  // eslint-disable-next-line no-restricted-syntax
  return (value: string) => new Date(value).toLocaleString(i18n.language);
}
