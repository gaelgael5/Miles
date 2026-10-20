import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

export interface Culture {
  code: string;
  label_en: string;
  label_native: string;
  active: boolean;
}

export const FALLBACK_CODE = "en-US";
const CULTURES_KEY = ["cultures"] as const;

/** Minuscules sans accents : le filtre ignore casse et diacritiques. */
export function foldForSearch(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export function matchesFilter(culture: Culture, filter: string): boolean {
  const needle = foldForSearch(filter.trim());
  if (needle === "") {
    return true;
  }
  return [culture.code, culture.label_en, culture.label_native].some((text) =>
    foldForSearch(text).includes(needle),
  );
}

export function useCultures() {
  return useQuery({
    queryKey: [...CULTURES_KEY, "all"],
    queryFn: ({ signal }) => request<Culture[]>("/api/cultures", { signal }),
  });
}

export function useActiveCultures() {
  return useQuery({
    queryKey: [...CULTURES_KEY, "active"],
    queryFn: ({ signal }) => request<Culture[]>("/api/cultures/active", { signal }),
  });
}

export function useSetCulturesActive() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { codes: string[]; active: boolean }) =>
      request<{ changed: string[] }>("/api/cultures/activation", {
        method: "POST",
        body: JSON.stringify(input),
      }),
    // Toutes les listes de cultures se relisent : les écrans de saisie aussi suivent.
    onSuccess: () => client.invalidateQueries({ queryKey: CULTURES_KEY }),
  });
}

/** Cultures actives, lisibles sans session : le sélecteur de l'écran de connexion. */
export function usePublicCultures() {
  return useQuery({
    queryKey: [...CULTURES_KEY, "public"],
    queryFn: ({ signal }) =>
      request<{ code: string; label_native: string }[]>("/api/auth/cultures", { signal }),
  });
}
