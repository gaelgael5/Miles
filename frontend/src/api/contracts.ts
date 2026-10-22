import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

/** Sortant : appel d'un service distant ; entrant : webhook reçu. Jamais de défaut. */
export type Direction = "sortant" | "entrant";

export interface Operation {
  method: string;
  path: string;
  operation_id: string | null;
}

export interface ContractVersion {
  number: number;
  /** null : fichier retouché hors de Miles et devenu illisible. */
  title: string | null;
  operations: number;
  warnings: string[];
}

export interface ContractVersionDetail extends ContractVersion {
  operation_list: Operation[];
}

export interface Contract {
  /** Figé à la déclaration : identifiant stable, jamais renommé. */
  slug: string;
  label: string;
  sens: Direction;
  /** Croissantes : les versions d'un contrat coexistent. */
  versions: ContractVersion[];
}

export interface ContractDetail extends Omit<Contract, "versions"> {
  versions: ContractVersionDetail[];
}

export interface ContractPreview {
  title: string;
  openapi: string;
  operations: Operation[];
  warnings: string[];
}

/**
 * Slug proposé d'après le label : minuscules sans accents, mots séparés par des tirets.
 * Simple proposition, modifiable : c'est le back-office qui valide le slug. Rend une
 * chaîne vide quand rien ne reste, pour qu'un slug soit donné plutôt qu'inventé.
 */
export function proposeSlug(label: string): string {
  const ascii = label.normalize("NFKD").replace(/[^\x20-\x7e]/g, "");
  const slug = ascii.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return slug.slice(0, 63).replace(/-+$/, "");
}

function root(workspaceId: string) {
  return `/api/workspaces/${encodeURIComponent(workspaceId)}/contracts`;
}

function key(workspaceId: string) {
  return ["contracts", workspaceId] as const;
}

/** `enabled` : le menu ne lit les contrats que d'un workspace déplié (un clone chacun). */
export function useContracts(workspaceId: string, enabled = true) {
  return useQuery({
    queryKey: key(workspaceId),
    enabled,
    queryFn: ({ signal }) => request<Contract[]>(root(workspaceId), { signal }),
  });
}

export function useContract(workspaceId: string, slug: string) {
  return useQuery({
    queryKey: [...key(workspaceId), slug],
    queryFn: ({ signal }) =>
      request<ContractDetail>(`${root(workspaceId)}/${encodeURIComponent(slug)}`, { signal }),
  });
}

/** Lecture du fichier sans rien écrire : montrée avant l'intégration. */
export function usePreviewContract(workspaceId: string) {
  return useMutation({
    mutationFn: (content: string) =>
      request<ContractPreview>(`${root(workspaceId)}/preview`, {
        method: "POST",
        body: JSON.stringify({ content }),
      }),
  });
}

export function useDeclareContract(workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { label: string; slug: string; sens: Direction }) =>
      request<Contract>(root(workspaceId), { method: "POST", body: JSON.stringify(input) }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(workspaceId) }),
  });
}

export function useImportVersion(workspaceId: string, slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (content: string) =>
      request<ContractVersionDetail>(
        `${root(workspaceId)}/${encodeURIComponent(slug)}/versions`,
        { method: "POST", body: JSON.stringify({ content }) },
      ),
    // Préfixe commun : la liste (menu compris) et le détail de ce contrat se rafraîchissent.
    onSuccess: () => client.invalidateQueries({ queryKey: key(workspaceId) }),
  });
}

/** Lecture d'un contrat publié à une adresse : le back-office le lit, rien n'est écrit. */
export function useFetchContract(workspaceId: string) {
  return useMutation({
    mutationFn: (url: string) =>
      request<{ content: string }>(`${root(workspaceId)}/fetch`, {
        method: "POST",
        body: JSON.stringify({ url }),
      }),
  });
}
