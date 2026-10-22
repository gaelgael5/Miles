import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "./http";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/** Une étape : un template, et la cible où poser son résultat (vide : il devient le message). */
export interface ChainStep {
  name: string;
  template: string;
  target: string | null;
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

export function useSaveChain(target: WorkTarget, slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { label: string; steps: ChainStep[] }) =>
      request<Chain>(atBranch(target, "transformations", slug), {
        method: "PUT",
        body: JSON.stringify(input),
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
