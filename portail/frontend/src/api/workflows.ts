import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "@miles/socle-web";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/** Un manquement du script, positionné comme le MOTEUR le positionne. */
export interface ScriptProblem {
  line: number;
  column: number;
  message: string;
}

/**
 * Un script de workflow de la branche.
 *
 * Un script COMPLET du DSL d'`urban-workflow`, par opposition aux artefacts de périmètre
 * que l'écran des types d'event écrit : il `INCLUDE` les périmètres dont il consomme les
 * types d'event, puis déclare ses états et ses transitions.
 *
 * `problems` non vide : le script ne se relit pas. Il est rendu quand même — c'est lui qui
 * empêchera d'enregistrer une version, et le masquer ferait chercher dans git.
 */
export interface Workflow {
  /** Le nom du fichier, qui est aussi le `NAME` du script quand les deux s'accordent. */
  name: string;
  /** Le `DESCRIPTION` du script ; null s'il n'en porte pas, ou s'il est illisible. */
  label: string | null;
  /**
   * Le `VERSION` du script, tenu par celui qui ÉCRIT et non par Miles : c'est une version
   * fonctionnelle du comportement, pas le numéro de révision d'un document.
   */
  version: number | null;
  /** Les noms de FICHIER inclus, dans l'ordre écrit — le chargeur les visite dans cet ordre. */
  includes: string[];
  states: number;
  problems: ScriptProblem[];
}

export interface WorkflowContent extends Workflow {
  content: string;
}

function root(target: WorkTarget) {
  return atBranch(target, "workflows");
}

function one(target: WorkTarget, name: string) {
  return atBranch(target, "workflows", name);
}

function key(target: WorkTarget) {
  return branchKey("workflows", target);
}

export function useWorkflows(target: WorkTarget) {
  return useQuery({
    queryKey: key(target),
    queryFn: ({ signal }) => request<Workflow[]>(root(target), { signal }),
  });
}

function useInvalidating<I, O>(target: WorkTarget, mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}

/** Crée un workflow réduit à son identité ; son corps s'écrit ensuite sur son écran. */
export function useCreateWorkflow(target: WorkTarget) {
  return useInvalidating(target, (input: { name: string; label: string }) =>
    request<Workflow>(root(target), { method: "POST", body: JSON.stringify(input) }),
  );
}

export function useDeleteWorkflow(target: WorkTarget) {
  return useInvalidating(target, (name: string) =>
    request<undefined>(one(target, name), { method: "DELETE" }),
  );
}
