import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@miles/socle-web";

/**
 * Le référentiel DONNÉ des pays : on n'y fait qu'activer et désactiver.
 *
 * Même dispositif que les cultures, et pour la même raison : 249 entrées ne se choisissent
 * pas dans une liste déroulante. L'administrateur retient celles dont son installation se
 * sert, et c'est son seul geste — aucune création, aucune suppression, aucun renommage.
 */
export interface Country {
  /** ISO 3166-1 alpha-3, le code qu'on écrit dans une procédure. */
  slug: string;
  /** L'alpha-2, parce que c'est lui que les systèmes tiers emploient le plus souvent. */
  alpha2: string;
  /**
   * Dérivé de CLDR par le serveur, dans la culture demandée. Jamais stocké, donc jamais
   * périmé : activer une culture de plus change ce libellé sans aucune migration.
   */
  label: string;
  active: boolean;
  /**
   * Le pays a-t-il un fichier de règles de jours fériés ? Dans la LISTE, pour que
   * l'association se voie sans déplier 249 pays un par un. Faux n'est pas une anomalie :
   * calendarium couvre 111 pays vérifiés.
   */
  has_holidays: boolean;
}

/** Un jour calculé par le moteur : sa date légale, le jour chômé, et ce qu'il est. */
export interface HolidayDay {
  /** Date civile ISO (« 2026-07-14 »), sans heure ni fuseau : une case de calendrier. */
  date: string;
  /** Le jour réellement chômé. Égal à `date` quand la règle ne reporte rien. */
  observed: string;
  name: string;
  /** Chômé ou non : toutes les périodes d'un fichier ne sont pas des jours de congé. */
  free: boolean;
  shifted: boolean;
}

export interface CountryHolidays {
  /** Le nom du pays chez calendarium, qui n'est pas le libellé affiché (`United_States`). */
  country: string;
  /** L'URL brute du fichier de règles, telle que la base la porte. */
  source_url: string;
  /** La page GitHub navigable : c'est celle qu'on clique. */
  page_url: string;
  start: string;
  end: string;
  days: HolidayDay[];
}

const COUNTRIES_KEY = ["countries"] as const;
// Clé SÉPARÉE de celle des pays, et non dérivée d'elle : activer un pays invalide la liste
// (`useSetCountriesActive`), et une clé dérivée ferait relire les jours fériés de chaque
// panneau ouvert — alors que l'activation ne change aucune règle de calendrier.
const HOLIDAYS_KEY = ["country-holidays"] as const;

/**
 * Les pays, filtrés PAR LE SERVEUR.
 *
 * Le filtre est côté serveur et non côté écran, à la différence des cultures : c'est lui
 * qui dérive les libellés, donc lui seul peut faire correspondre « allemagne » à `DEU`.
 * Refaire le repli de casse et d'accents ici donnerait deux implémentations du même
 * filtre, dont une seule verrait les libellés.
 *
 * `keepPreviousData` : la liste ne clignote pas pendant qu'on tape.
 */
export function useCountries(input: { culture: string; search: string; onlyActive?: boolean }) {
  const params = new URLSearchParams({ culture: input.culture });
  if (input.search.trim() !== "") {
    params.set("q", input.search.trim());
  }
  if (input.onlyActive) {
    params.set("only_active", "true");
  }
  return useQuery({
    queryKey: [...COUNTRIES_KEY, input.culture, input.search.trim(), input.onlyActive ?? false],
    queryFn: ({ signal }) => request<Country[]>(`/api/countries?${params.toString()}`, { signal }),
    placeholderData: keepPreviousData,
  });
}

export function useSetCountriesActive() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { slugs: string[]; active: boolean }) =>
      request<{ changed: string[] }>("/api/countries/activation", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    // Toutes les lectures de pays se relisent, quelle que soit la culture ou le filtre.
    onSuccess: () => client.invalidateQueries({ queryKey: COUNTRIES_KEY }),
  });
}

/**
 * Les règles de jours fériés d'un pays et les jours des 12 prochains mois.
 *
 * Les jours sont CALCULÉS par le serveur à chaque lecture, jamais stockés : une fenêtre
 * stockée demanderait de savoir quand la rafraîchir, pour une fonction qui coûte moins
 * d'une milliseconde par année.
 *
 * Le hook ne se monte que lorsqu'un panneau est déplié — comme celui des fuseaux : 249
 * pays dépliés d'office feraient 249 calculs que personne ne regarde.
 */
export function useCountryHolidays(slug: string) {
  return useQuery({
    queryKey: [...HOLIDAYS_KEY, slug],
    queryFn: ({ signal }) =>
      request<CountryHolidays>(`/api/countries/${encodeURIComponent(slug)}/holidays`, { signal }),
  });
}
