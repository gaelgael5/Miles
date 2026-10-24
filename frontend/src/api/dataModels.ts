import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/** Emplacement d'un modèle : « shared » pour un transverse, sinon le nom du domaine. */
export interface DataModel {
  scope: string;
  name: string;
  path: string;
  /** Le `title` du schéma ; null s'il n'en porte pas. */
  label: string | null;
  /** Tenue par le système : 1 à la création, +1 à chaque enregistrement qui le change. */
  version: number | null;
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

export type SampleFormat = "json" | "yaml";

/** Déduit un schéma d'un échantillon. Rien n'est écrit : le résultat part dans l'éditeur,
 * et n'atteint le dépôt que si la personne enregistre le modèle. */
export function useInferSchema(target: WorkTarget) {
  return useMutation({
    mutationFn: (body: { format: SampleFormat; sample: string }) =>
      request<{ schema: Record<string, unknown>; unwrapped: boolean }>(
        atBranch(target, "data-models", "inference"),
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      ),
  });
}

export function useDataModels(target: WorkTarget) {
  return useQuery({
    queryKey: key(target),
    queryFn: ({ signal }) => request<DataModel[]>(root(target), { signal }),
  });
}

type ModelRef = Pick<DataModel, "scope" | "name">;

/** La lecture d'un modèle, partagée par l'écran et l'aperçu des `$ref` de l'éditeur. */
export function modelQuery(target: WorkTarget, model: ModelRef) {
  return {
    queryKey: [...key(target), model.scope, model.name],
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      request<DataModelContent>(one(target, model.scope, model.name), { signal }),
  };
}

export function useDataModel(target: WorkTarget, model: ModelRef) {
  return useQuery(modelQuery(target, model));
}

function useInvalidating<I, O>(target: WorkTarget, mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}

/** Déclare un modèle par label et slug (Gael, 23/10/2026) : un brouillon sans propriété. */
export function useDeclareDataModel(target: WorkTarget) {
  return useInvalidating(target, (input: { scope: string; label: string; slug: string }) =>
    request<DataModel>(atBranch(target, "data-models", "declarations"), {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
}

/** Remplace le YAML d'un modèle ; son nom (le slug) ne change pas. */
export function useReplaceDataModel(target: WorkTarget, model: ModelRef) {
  return useInvalidating(target, (content: string) =>
    request<DataModel>(one(target, model.scope, model.name), {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
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
