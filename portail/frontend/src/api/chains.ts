import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "@miles/socle-web";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/** Un écart entre ce que le template ÉCRIT et le modèle de destination qu'il annonce. */
export interface StepAlert {
  /** Chemin dans le RÉSULTAT de l'étape, pas dans le template. */
  path: string;
  code: string;
  detail: string | null;
}

/** Une étape : un template, et la cible où poser son résultat (vide : il devient le message). */
export interface ChainStep {
  name: string;
  template: string;
  target: string | null;
  /** URI des modèles que l'étape lit et produit ; null tant qu'ils ne sont pas choisis. */
  source_model: string | null;
  destination_model: string | null;
  /**
   * Calculées par le serveur à chaque lecture, jamais écrites. Absentes d'une étape que
   * l'écran vient d'ajouter : elle n'a pas encore été confrontée à quoi que ce soit.
   */
  alerts?: StepAlert[];
}

export interface Chain {
  /** Figé à la création : les flux désignent la chaîne par lui. */
  slug: string;
  label: string;
  /** Dans l'ordre d'application, choisi par l'utilisateur. */
  steps: ChainStep[];
}

export interface ChainSummary {
  slug: string;
  /** null : enchaînement illisible, retouché hors de Miles. */
  label: string | null;
  steps: number | null;
}

/** Un défaut d'une étape, avec son rang (0 pour la première). */
export interface StepProblem {
  step: number;
  code: string;
  detail: string | null;
  line: number | null;
  column: number | null;
  violations: { construction: string; detail: string | null; line: number | null; column: number | null }[];
}

export interface ChainCheck {
  valid: boolean;
  problems: StepProblem[];
  /** Message après chaque étape. */
  trace: unknown[];
  failure: {
    step: number;
    evaluation: { code: string; message: string | null; path: string | null; expected: string | null };
  } | null;
}

function key(target: WorkTarget) {
  return branchKey("chains", target);
}

/** L'échantillon source de test : en base, jamais dans git (Gael, 24/10/2026). */
export function useChainSample(target: WorkTarget, slug: string) {
  return useQuery({
    queryKey: [...branchKey("chain-sample", target), slug],
    queryFn: ({ signal }) =>
      request<{ sample: string | null }>(sampleRoute(target, slug), { signal }),
  });
}

export function useSaveChainSample(target: WorkTarget, slug: string) {
  const client = useQueryClient();
  return useMutation({
    // null efface : l'écran n'a pas besoin d'un second geste pour retirer l'échantillon.
    mutationFn: (sample: string | null) =>
      request<{ sample: string | null }>(sampleRoute(target, slug), {
        method: "PUT",
        body: JSON.stringify({ sample }),
      }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: [...branchKey("chain-sample", target), slug] }),
  });
}

function sampleRoute(target: WorkTarget, slug: string) {
  return atBranch(target, "transformations", slug, "sample");
}

export function useChains(target: WorkTarget, enabled = true) {
  return useQuery({
    queryKey: key(target),
    enabled,
    queryFn: ({ signal }) => request<ChainSummary[]>(atBranch(target, "transformations"), { signal }),
  });
}

export function useChain(target: WorkTarget, slug: string) {
  return useQuery({
    queryKey: [...key(target), slug],
    queryFn: ({ signal }) => request<Chain>(atBranch(target, "transformations", slug), { signal }),
  });
}

/**
 * Ce qui s'ÉCRIT d'une étape, et rien d'autre.
 *
 * L'API refuse tout champ qu'elle ne connaît pas, et les alertes lues avec la chaîne
 * voyagent dans les mêmes objets que l'écran garde en état : les renvoyer telles quelles
 * ferait refuser l'enregistrement d'une étape pourtant intacte.
 */
function written(step: ChainStep) {
  return {
    name: step.name,
    template: step.template,
    target: step.target,
    source_model: step.source_model,
    destination_model: step.destination_model,
  };
}

export function useSaveChain(target: WorkTarget, slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { label: string; steps: ChainStep[] }) =>
      request<Chain>(atBranch(target, "transformations", slug), {
        method: "PUT",
        body: JSON.stringify({ label: input.label, steps: input.steps.map(written) }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}

export function useDeleteChain(target: WorkTarget, slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<undefined>(atBranch(target, "transformations", slug), { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}

/** Essai sur un échantillon, sans rien écrire. */
export function useCheckChain() {
  return useMutation({
    mutationFn: (input: { steps: { template: string; target: string | null }[]; sample: unknown }) =>
      request<ChainCheck>("/api/transformations/check", {
        method: "POST",
        body: JSON.stringify(input),
      }),
  });
}
