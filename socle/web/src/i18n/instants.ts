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

/**
 * Formate une DURÉE en millisecondes dans la culture de l'interface.
 *
 * Deuxième point unique de formatage du même module, et pour la même raison que les
 * instants : les unités se disent différemment d'une culture à l'autre, et les écrire en
 * dur les figerait en français. `Intl.NumberFormat` avec `style: "unit"` est l'API qui
 * les rend, et c'est l'une des rares que la règle `no-restricted-syntax` du dépôt laisse
 * passer — elle prend la culture en argument, là où `toLocaleString` prend celle du
 * navigateur.
 *
 * Sous la minute, une décimale : un import de huit secondes et un de huit secondes et
 * demie ne se comparent pas sans elle. Au-delà, la seconde entière suffit — personne ne
 * lit « 2 min 11,4 s ».
 */
export function useDuration(): (milliseconds: number) => string {
  const { i18n } = useTranslation();
  const secondes = new Intl.NumberFormat(i18n.language, {
    style: "unit",
    unit: "second",
    maximumFractionDigits: 1,
  });
  const minutes = new Intl.NumberFormat(i18n.language, { style: "unit", unit: "minute" });

  return (milliseconds: number) => {
    if (milliseconds < 60_000) {
      return secondes.format(milliseconds / 1000);
    }
    const entières = Math.floor(milliseconds / 60_000);
    return `${minutes.format(entières)} ${secondes.format(Math.round((milliseconds % 60_000) / 1000))}`;
  };
}

/**
 * Formate une DATE CIVILE (« 2026-07-14 ») dans la culture de l'interface.
 *
 * TROISIÈME point unique de ce module, et il ne se confond pas avec `useInstant` — deux
 * défauts distincts l'imposent, et il faut les deux pour comprendre pourquoi ce n'est pas
 * une redite.
 *
 * **Le décalage d'un jour.** Une chaîne de date seule est parsée par ECMAScript comme
 * minuit **UTC**. Affichée ensuite dans le fuseau du navigateur, elle recule d'un jour
 * partout à l'ouest de Greenwich : le 14 juillet d'un jour férié français s'afficherait
 * « 13 juillet » à Montréal. D'où `timeZone: "UTC"`, qui est la garde et non un détail —
 * la date n'a pas de fuseau, c'est une case de calendrier.
 *
 * **L'heure qu'il ne faut pas montrer.** `useInstant` rend date ET heure ; un jour férié
 * s'afficherait « 14/07/2026 00:00:00 », où le minuit est un artefact du transport.
 *
 * `Intl.DateTimeFormat` prend la culture en ARGUMENT, là où `toLocaleDateString` prend
 * celle du navigateur : c'est pourquoi la règle `no-restricted-syntax` du dépôt laisse
 * passer la première et interdit la seconde.
 *
 * Le jour de la semaine est inclus : sur un calendrier de jours fériés, savoir qu'une fête
 * tombe un samedi est précisément ce qu'on vient y lire.
 */
export function useCalendarDate(): (value: string) => string {
  const { i18n } = useTranslation();
  const format = new Intl.DateTimeFormat(i18n.language, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
  return (value: string) => format.format(new Date(`${value}T00:00:00Z`));
}
