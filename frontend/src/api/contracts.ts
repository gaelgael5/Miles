import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

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
  /** null : version déposée hors de Miles, sans date ni auteur connus. */
  imported_at: string | null;
  imported_by: string | null;
}

export interface VersionOperation extends Operation {
  /** « nouvelle » : absente de la version précédente. */
  change: "nouvelle" | null;
}

export interface ContractVersionDetail extends ContractVersion {
  operation_list: VersionOperation[];
  /** Version comparée ; null pour la première. */
  compared_with: number | null;
  /** Exposées par la précédente, plus par celle-ci : leurs mappings servent encore. */
  removed: Operation[];
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

function key(target: WorkTarget) {
  return branchKey("contracts", target);
}

/** `enabled` : le menu ne lit les contrats que d'une branche dépliée (un clone chacune). */
export function useContracts(target: WorkTarget, enabled = true) {
  return useQuery({
    queryKey: key(target),
    enabled,
    queryFn: ({ signal }) => request<Contract[]>(atBranch(target, "contracts"), { signal }),
  });
}

export function useContract(target: WorkTarget, slug: string) {
  return useQuery({
    queryKey: [...key(target), slug],
    queryFn: ({ signal }) =>
      request<ContractDetail>(atBranch(target, "contracts", slug), { signal }),
  });
}

/** Lecture du fichier sans rien écrire : montrée avant l'intégration. */
export function usePreviewContract(target: WorkTarget) {
  return useMutation({
    mutationFn: (content: string) =>
      request<ContractPreview>(atBranch(target, "contracts", "preview"), {
        method: "POST",
        body: JSON.stringify({ content }),
      }),
  });
}

export function useDeclareContract(target: WorkTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { label: string; slug: string; sens: Direction }) =>
      request<Contract>(atBranch(target, "contracts"), {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}

export function useImportVersion(target: WorkTarget, slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (content: string) =>
      request<ContractVersionDetail>(atBranch(target, "contracts", slug, "versions"), {
        method: "POST",
        body: JSON.stringify({ content }),
      }),
    // Préfixe commun : la liste (menu compris) et le détail de ce contrat se rafraîchissent.
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}

/** Supprime le contrat entier, déclaration et versions (ticket 6e15d4cd). */
export function useDeleteContract(target: WorkTarget, slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<undefined>(atBranch(target, "contracts", slug), { method: "DELETE" }),
    onSuccess: () => {
      // Le détail n'existe plus : on l'oublie plutôt que de le relire pour un 404.
      client.removeQueries({ queryKey: [...key(target), slug] });
      return client.invalidateQueries({ queryKey: key(target) });
    },
  });
}

/** Lecture d'un contrat publié à une adresse : le back-office le lit, rien n'est écrit. */
export function useFetchContract(target: WorkTarget) {
  return useMutation({
    mutationFn: (url: string) =>
      request<{ content: string }>(atBranch(target, "contracts", "fetch"), {
        method: "POST",
        body: JSON.stringify({ url }),
      }),
  });
}
