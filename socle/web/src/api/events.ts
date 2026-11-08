import { useQuery } from "@tanstack/react-query";

import { request } from "./http";

export interface EventObject {
  kind: string;
  id: string;
  sequence: number;
}

export interface JournalEvent {
  id: string;
  type: string;
  functional_at: string;
  /** « write_time » : l'appelant n'avait pas de date métier, et le lecteur doit le savoir. */
  functional_at_source: string;
  written_at: string;
  author_directory: string;
  author_subject: string;
  properties: Record<string, unknown>;
  objects: EventObject[];
}

export interface EventWindow {
  start: string;
  end: string;
  /** Vrai quand aucune borne n'a été demandée : l'écran DOIT le dire. */
  defaulted: boolean;
}

export interface EventsPage {
  events: JournalEvent[];
  total: number;
  page: number;
  size: number;
  window: EventWindow;
  missing_sequences: number[];
}

export interface EventsFilter {
  type?: string;
  author_directory?: string;
  author_subject?: string;
  object_kind?: string;
  object_id?: string;
  written_from?: string;
  written_to?: string;
  functional_from?: string;
  functional_to?: string;
}

export const EVENTS_PAGE_SIZE = 50;

/** Les filtres vides sont RETIRÉS, jamais envoyés à blanc : `?type=` filtrerait sur la
 * chaîne vide et ne rendrait rien, ce qui se lit comme un journal vide. */
export function eventsQuery(filter: EventsFilter, page: number): string {
  const params = new URLSearchParams();
  for (const [clef, valeur] of Object.entries(filter)) {
    if (typeof valeur === "string" && valeur.trim() !== "") {
      params.set(clef, valeur.trim());
    }
  }
  params.set("page", String(page));
  params.set("size", String(EVENTS_PAGE_SIZE));
  return params.toString();
}

export const EVENTS_REFRESH_MS = 20_000;

/**
 * Toutes les vingt secondes, et SEULEMENT sur la première page (Gael, 08/11/2026).
 *
 * Le journal se regarde pendant qu'il se remplit : un import de fichier écrit un event
 * par objet rangé, donc la tête du journal EST la progression de l'import. Sans
 * rafraîchissement, il faut recharger l'écran à la main pour voir qu'il avance.
 *
 * Pas au-delà de la première page, et ce n'est pas une prudence : le journal est trié du
 * plus récent au plus ancien, donc chaque event qui arrive pousse tout le reste d'un
 * rang. Rafraîchir la page 3 déplacerait les lignes sous l'œil de celui qui les lit —
 * la pagination n'est plus une tête qu'on surveille, c'est une position de lecture.
 */
export function refreshInterval(page: number): number | false {
  return page === 1 ? EVENTS_REFRESH_MS : false;
}

export function useEvents(filter: EventsFilter, page: number) {
  const query = eventsQuery(filter, page);
  return useQuery({
    // La requête ENTIÈRE dans la clef : deux filtres différents sont deux lectures
    // différentes, et partager leur cache ferait afficher le résultat de l'autre.
    queryKey: ["events", query],
    queryFn: ({ signal }) => request<EventsPage>(`/api/events?${query}`, { signal }),
    // `refetchIntervalInBackground` reste à son défaut, FAUX : un onglet qu'on ne
    // regarde pas n'interroge pas le serveur, et la reprise se fait au retour.
    refetchInterval: refreshInterval(page),
  });
}
