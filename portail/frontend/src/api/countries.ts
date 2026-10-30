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
}

const COUNTRIES_KEY = ["countries"] as const;

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
