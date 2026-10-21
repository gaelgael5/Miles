import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";

/** Emplacement d'un modèle : « shared » pour un transverse, sinon le nom du domaine. */
export interface DataModel {
  scope: string;
  name: string;
  path: string;
}

export interface DataModelContent extends DataModel {
  content: string;
}

/** Un manquement à la grammaire, désigné par son chemin dans le document. */
export interface ModelProblem {
  path: string;
  code: string;
  detail: string | null;
}

export const SHARED_SCOPE = "shared";

function root(workspaceId: string) {
  return `/api/workspaces/${encodeURIComponent(workspaceId)}/data-models`;
}

function one(workspaceId: string, scope: string, name: string) {
  return `${root(workspaceId)}/${encodeURIComponent(scope)}/${encodeURIComponent(name)}`;
}

function key(workspaceId: string) {
  return ["data-models", workspaceId] as const;
}

export function useDataModels(workspaceId: string) {
  return useQuery({
    queryKey: key(workspaceId),
    queryFn: ({ signal }) => request<DataModel[]>(root(workspaceId), { signal }),
  });
}

export function useDataModel(workspaceId: string, model: DataModel | null) {
  return useQuery({
    queryKey: [...key(workspaceId), model?.path],
    enabled: model !== null,
    queryFn: ({ signal }) =>
      request<DataModelContent>(one(workspaceId, model?.scope ?? "", model?.name ?? ""), {
        signal,
      }),
  });
}

function useInvalidating<I, O>(workspaceId: string, mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => client.invalidateQueries({ queryKey: key(workspaceId) }),
  });
}

export function useCreateDataModel(workspaceId: string) {
  return useInvalidating(workspaceId, (input: { scope: string; content: string }) =>
    request<DataModel>(root(workspaceId), { method: "POST", body: JSON.stringify(input) }),
  );
}

export function useDeleteDataModel(workspaceId: string) {
  return useInvalidating(workspaceId, (model: DataModel) =>
    request<undefined>(one(workspaceId, model.scope, model.name), { method: "DELETE" }),
  );
}
