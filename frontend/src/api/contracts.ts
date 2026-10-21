import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

/** Sortant : appel d'un service distant ; entrant : webhook reçu. Jamais de défaut. */
export type Direction = "sortant" | "entrant";

export interface Operation {
  method: string;
  path: string;
  operation_id: string | null;
}

export interface Contract {
  /** Figé à la création : identifiant stable, jamais renommé. */
  slug: string;
  sens: Direction;
  title: string;
  operations: number;
  warnings: string[];
}

export interface ContractDetail extends Contract {
  operation_list: Operation[];
}

export interface ContractPreview {
  slug: string;
  title: string;
  openapi: string;
  operations: Operation[];
  warnings: string[];
}

function root(workspaceId: string) {
  return `/api/workspaces/${encodeURIComponent(workspaceId)}/contracts`;
}

function key(workspaceId: string) {
  return ["contracts", workspaceId] as const;
}

export function useContracts(workspaceId: string) {
  return useQuery({
    queryKey: key(workspaceId),
    queryFn: ({ signal }) => request<Contract[]>(root(workspaceId), { signal }),
  });
}

export function useContract(workspaceId: string, slug: string | null) {
  return useQuery({
    queryKey: [...key(workspaceId), slug],
    enabled: slug !== null,
    queryFn: ({ signal }) =>
      request<ContractDetail>(`${root(workspaceId)}/${encodeURIComponent(slug ?? "")}`, {
        signal,
      }),
  });
}

/** Lecture du contrat sans rien écrire : le slug proposé se corrige avant l'import. */
export function usePreviewContract(workspaceId: string) {
  return useMutation({
    mutationFn: (content: string) =>
      request<ContractPreview>(`${root(workspaceId)}/preview`, {
        method: "POST",
        body: JSON.stringify({ content }),
      }),
  });
}

export function useImportContract(workspaceId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { slug: string; sens: Direction; content: string }) =>
      request<Contract>(root(workspaceId), { method: "POST", body: JSON.stringify(input) }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(workspaceId) }),
  });
}
