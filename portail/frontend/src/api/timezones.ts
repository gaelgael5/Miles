import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@miles/socle-web";

/**
 * Le référentiel DONNÉ des fuseaux horaires : jumeau de celui des pays.
 *
 * 312 zones canoniques de la table IANA, et l'administrateur retient celles dont son
 * installation se sert. Aucune création, aucune suppression, aucun renommage.
 */
export interface Timezone {
  /**
   * L'identifiant IANA (`Europe/Paris`). Affiché TOUJOURS, à côté du libellé : CLDR rend
   * un nom de métazone — « heure d'Europe centrale » vaut pour Paris, Berlin et Madrid —
   * donc le libellé seul ne désigne aucun fuseau.
   */
  slug: string;
  label: string;
  /**
   * TOUS les pays du fuseau, par leur slug alpha-3, dans l'ordre d'IANA. Jamais vide : la
   * table IANA donne au moins un pays à chacune de ses zones. `Europe/Paris` en a deux —
   * la France et Monaco.
   */
  countries: string[];
  active: boolean;
}

const TIMEZONES_KEY = ["timezones"] as const;

/** Les fuseaux, filtrés PAR LE SERVEUR — c'est lui qui dérive les libellés. */
export function useTimezones(input: {
  culture: string;
  search: string;
  country?: string;
  onlyActive?: boolean;
}) {
  const params = new URLSearchParams({ culture: input.culture });
  if (input.search.trim() !== "") {
    params.set("q", input.search.trim());
  }
  if (input.country !== undefined && input.country !== "") {
    params.set("country", input.country);
  }
  if (input.onlyActive) {
    params.set("only_active", "true");
  }
  return useQuery({
    queryKey: [
      ...TIMEZONES_KEY,
      input.culture,
      input.search.trim(),
      input.country ?? "",
      input.onlyActive ?? false,
    ],
    queryFn: ({ signal }) => request<Timezone[]>(`/api/timezones?${params.toString()}`, { signal }),
    placeholderData: keepPreviousData,
  });
}

export function useSetTimezonesActive() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { slugs: string[]; active: boolean }) =>
      request<{ changed: string[] }>("/api/timezones/activation", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: TIMEZONES_KEY }),
  });
}
