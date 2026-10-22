import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

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

function root(target: WorkTarget) {
  return atBranch(target, "data-models");
}

function one(target: WorkTarget, scope: string, name: string) {
  return atBranch(target, "data-models", scope, name);
}

function key(target: WorkTarget) {
  return branchKey("data-models", target);
}

export function useDataModels(target: WorkTarget) {
  return useQuery({
    queryKey: key(target),
    queryFn: ({ signal }) => request<DataModel[]>(root(target), { signal }),
  });
}

export function useDataModel(target: WorkTarget, model: DataModel | null) {
  return useQuery({
    queryKey: [...key(target), model?.path],
    enabled: model !== null,
    queryFn: ({ signal }) =>
      request<DataModelContent>(one(target, model?.scope ?? "", model?.name ?? ""), {
        signal,
      }),
  });
}

function useInvalidating<I, O>(target: WorkTarget, mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}

export function useCreateDataModel(target: WorkTarget) {
  return useInvalidating(target, (input: { scope: string; content: string }) =>
    request<DataModel>(root(target), { method: "POST", body: JSON.stringify(input) }),
  );
}

export function useDeleteDataModel(target: WorkTarget) {
  return useInvalidating(target, (model: DataModel) =>
    request<undefined>(one(target, model.scope, model.name), { method: "DELETE" }),
  );
}

/** Version enregistrée : une étiquette `version/<n>`, numéro unique au dépôt. */
export interface SavedVersion {
  number: number;
  label: string;
  commit: string;
  author: string;
  saved_at: string;
  /** Branche git d'où vient la version ; null : posée avant les branches filles. */
  branch: string | null;
}

function versionsKey(target: WorkTarget) {
  return branchKey("versions", target);
}

export function useVersions(target: WorkTarget) {
  return useQuery({
    queryKey: versionsKey(target),
    queryFn: ({ signal }) => request<SavedVersion[]>(atBranch(target, "versions"), { signal }),
  });
}

export function useSaveVersion(target: WorkTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (label: string) =>
      request<SavedVersion>(atBranch(target, "versions"), {
        method: "POST",
        body: JSON.stringify({ label }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: versionsKey(target) }),
  });
}

export function useRestoreVersion(target: WorkTarget) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (number: number) =>
      request<{ commit: string }>(atBranch(target, "versions", String(number), "restore"), {
        method: "POST",
      }),
    // Le retour réécrit l'arbre de la branche : modèles et contrats listés changent aussi.
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: versionsKey(target) }),
        client.invalidateQueries({ queryKey: key(target) }),
        client.invalidateQueries({ queryKey: branchKey("contracts", target) }),
      ]),
  });
}
