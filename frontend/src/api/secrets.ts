import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

export interface Consumer {
  kind: string;
  id: string;
}

/** Ce que l'API rend d'un secret : jamais sa valeur, qui ne revient pas du serveur. */
export interface SecretSummary {
  slug: string;
  label: string;
  secret_type: string;
  created_at: string;
  updated_at: string;
  consumers: Consumer[];
}

export interface SecretInput {
  slug: string;
  label: string;
  secret_type: string;
  value: string;
}

const SECRETS_KEY = ["secrets"] as const;
const SLUG_MAX = 63;

/** Slug proposé depuis le libellé : minuscules sans accents, tirets, 63 caractères au plus. */
export function slugFromLabel(label: string): string {
  return label
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, SLUG_MAX)
    .replace(/-+$/, "");
}

function secretPath(slug: string) {
  return `/api/secrets/${encodeURIComponent(slug)}`;
}

/** Types admis, servis par l'API : le champ « type » est une liste, jamais une saisie. */
export function useSecretTypes(enabled = true) {
  return useQuery({
    enabled,
    queryKey: [...SECRETS_KEY, "types"],
    queryFn: ({ signal }) => request<{ types: string[] }>("/api/secret-types", { signal }),
    staleTime: Infinity,
  });
}

export function useSecrets(secretType?: string) {
  return useQuery({
    queryKey: [...SECRETS_KEY, secretType ?? null],
    queryFn: ({ signal }) => {
      const query = secretType ? `?secret_type=${encodeURIComponent(secretType)}` : "";
      return request<SecretSummary[]>(`/api/secrets${query}`, { signal });
    },
  });
}

function useSecretMutation<I, O>(mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    // La liste se relit au serveur : il est seul à savoir ce qui a été enregistré.
    onSuccess: () => client.invalidateQueries({ queryKey: SECRETS_KEY }),
  });
}

export function useCreateSecret() {
  return useSecretMutation((input: SecretInput) =>
    request<SecretSummary>("/api/secrets", { method: "POST", body: JSON.stringify(input) }),
  );
}

export function useRelabelSecret() {
  return useSecretMutation(({ slug, label }: { slug: string; label: string }) =>
    request<SecretSummary>(secretPath(slug), {
      method: "PATCH",
      body: JSON.stringify({ label }),
    }),
  );
}

export function useReplaceSecretValue() {
  return useSecretMutation(({ slug, value }: { slug: string; value: string }) =>
    request<undefined>(`${secretPath(slug)}/value`, {
      method: "PUT",
      body: JSON.stringify({ value }),
    }),
  );
}

export function useDeleteSecret() {
  return useSecretMutation((slug: string) =>
    request<undefined>(secretPath(slug), { method: "DELETE" }),
  );
}
