import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "@miles/socle-web";

import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/** Une clé d'un contexte, et ses valeurs dans les cultures du workspace. */
export interface TradsKey {
  slug: string;
  /**
   * Seules les cultures qui portent une valeur. Une culture absente n'est PAS traduite ;
   * elle n'apparaît jamais avec une chaîne vide, qui serait une valeur.
   */
  values: Record<string, string>;
}

export interface KeyPage {
  keys: TradsKey[];
  /** Total après filtre : l'écran sait combien de clés restent sans tout charger. */
  total: number;
}

/** Ce que la saisie envoie : `null` vide une valeur, une culture absente n'est pas touchée. */
export type ValueChanges = Record<string, string | null>;

export interface KeyFilter {
  search: string;
  /** Code de culture : ne ramener que les clés sans valeur dedans. */
  untranslated: string | null;
  offset: number;
  limit: number;
}

export const PAGE_SIZE = 50;

const KIND = "trads-keys";

function keysKey(target: WorkTarget, context: string, filter?: KeyFilter) {
  const base = [...branchKey(KIND, target), context] as const;
  return filter ? [...base, filter.search, filter.untranslated, filter.offset] : base;
}

function keysPath(target: WorkTarget, context: string, ...tail: string[]) {
  return atBranch(target, "trads", context, "keys", ...tail);
}

export function useTradsKeys(target: WorkTarget, context: string, filter: KeyFilter) {
  return useQuery({
    queryKey: keysKey(target, context, filter),
    queryFn: ({ signal }) => {
      const query = new URLSearchParams({
        search: filter.search,
        offset: String(filter.offset),
        limit: String(filter.limit),
      });
      if (filter.untranslated !== null) {
        query.set("untranslated", filter.untranslated);
      }
      return request<KeyPage>(`${keysPath(target, context)}&${query.toString()}`, { signal });
    },
  });
}

function useKeyMutation<TInput>(
  target: WorkTarget,
  context: string,
  send: (input: TInput) => Promise<unknown>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: send,
    // Toute la page se relit : une valeur vidée change aussi la couverture de la ligne.
    onSuccess: () => client.invalidateQueries({ queryKey: keysKey(target, context) }),
  });
}

export function useAddTradsKey(target: WorkTarget, context: string) {
  return useKeyMutation(target, context, (input: { slug: string; values: ValueChanges }) =>
    request<{ slug: string }>(keysPath(target, context), {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
}

export function useSaveTradsValues(target: WorkTarget, context: string) {
  return useKeyMutation(target, context, (input: { slug: string; values: ValueChanges }) =>
    request<{ slug: string }>(keysPath(target, context, input.slug), {
      method: "PUT",
      body: JSON.stringify({ values: input.values }),
    }),
  );
}

/** Action distincte de l'édition : elle peut casser des références qu'on ne sait pas voir. */
export function useRenameTradsKey(target: WorkTarget, context: string) {
  return useKeyMutation(target, context, (input: { slug: string; newSlug: string }) =>
    request<{ slug: string }>(keysPath(target, context, input.slug, "rename"), {
      method: "POST",
      body: JSON.stringify({ new_slug: input.newSlug }),
    }),
  );
}

export function useDeleteTradsKey(target: WorkTarget, context: string) {
  return useKeyMutation(target, context, (slug: string) =>
    request<{ slug: string }>(keysPath(target, context, slug), { method: "DELETE" }),
  );
}

/** Marques de direction présentes dans une valeur : l'éditeur les rend visibles. */
const MARKS: Record<string, string> = {
  "‎": "LRM",
  "‏": "RLM",
  "؜": "ALM",
};

export function marksIn(value: string): string[] {
  return [...new Set([...value].filter((c) => c in MARKS).map((c) => MARKS[c] as string))];
}
