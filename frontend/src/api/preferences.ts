import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

/** Préférences de la personne connectée, retenues côté serveur pour son compte. */
export interface Preferences {
  /** null : aucun choix ; le portail suit l'écran de connexion, puis en-US. */
  language: string | null;
}

const ROUTE = "/api/auth/me/preferences";
const KEY = ["preferences"] as const;

export function usePreferences() {
  return useQuery({
    queryKey: KEY,
    queryFn: ({ signal }) => request<Preferences>(ROUTE, { signal }),
  });
}

export function useSetLanguage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (language: string) =>
      request<Preferences>(ROUTE, { method: "PUT", body: JSON.stringify({ language }) }),
    onSuccess: (saved) => client.setQueryData(KEY, saved),
  });
}
