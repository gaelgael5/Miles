import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "@miles/socle-web";
import type { ModelProblem } from "./dataModels";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/**
 * Un événement de workflow : un JSON Schema écrit en YAML, comme un modèle de données,
 * mais dans sa propre liste (Gael, 11/11/2026) — un storage ne peut pas le désigner.
 *
 * `workflow-events` et non `events` : `/api/events` est déjà le journal d'audit.
 */
export interface WorkflowEvent {
  /** « shared » pour un événement transverse, sinon le nom du domaine. */
  scope: string;
  name: string;
  path: string;
  /** Le `title` du schéma ; null s'il n'en porte pas. */
  label: string | null;
  /** Tenue par le système : 1 à la déclaration, +1 à chaque enregistrement. */
  version: number | null;
}

export interface WorkflowEventContent extends WorkflowEvent {
  content: string;
}

/** Une propriété du socle commun, que le moteur valide EN PLUS du schéma métier. */
export interface SocleField {
  name: string;
  type: string;
  /** Posée par le moteur à l'intégration : une valeur de l'émetteur est ignorée. */
  read_only: boolean;
}

export type { ModelProblem };

function root(target: WorkTarget) {
  return atBranch(target, "workflow-events");
}

function one(target: WorkTarget, scope: string, name: string) {
  return atBranch(target, "workflow-events", scope, name);
}

function key(target: WorkTarget) {
  return branchKey("workflow-events", target);
}

export function useWorkflowEvents(target: WorkTarget) {
  return useQuery({
    queryKey: key(target),
    queryFn: ({ signal }) => request<WorkflowEvent[]>(root(target), { signal }),
  });
}

type EventRef = Pick<WorkflowEvent, "scope" | "name">;

export function useWorkflowEvent(target: WorkTarget, event: EventRef) {
  return useQuery({
    queryKey: [...key(target), event.scope, event.name],
    queryFn: ({ signal }) =>
      request<WorkflowEventContent>(one(target, event.scope, event.name), { signal }),
  });
}

/**
 * Le socle commun des événements, SERVI par le portail.
 *
 * Clef de requête à part de celle des événements : la liste vient du moteur installé, pas
 * de la branche — déclarer un événement ne la change pas, et elle n'a pas à être relue.
 */
export function useEventSocle(target: WorkTarget) {
  return useQuery({
    queryKey: ["workflow-event-socle"],
    queryFn: ({ signal }) =>
      request<SocleField[]>(atBranch(target, "workflow-events", "socle"), { signal }),
  });
}

function useInvalidating<I, O>(target: WorkTarget, mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}

/** Déclare un événement par libellé et nom : un objet sans propriété métier. */
export function useDeclareWorkflowEvent(target: WorkTarget) {
  return useInvalidating(target, (input: { scope: string; label: string; slug: string }) =>
    request<WorkflowEvent>(atBranch(target, "workflow-events", "declarations"), {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
}

/** Remplace le YAML d'un événement ; son nom ne change pas. */
export function useReplaceWorkflowEvent(target: WorkTarget, event: EventRef) {
  return useInvalidating(target, (content: string) =>
    request<WorkflowEvent>(one(target, event.scope, event.name), {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  );
}

export function useDeleteWorkflowEvent(target: WorkTarget) {
  return useInvalidating(target, (event: WorkflowEvent) =>
    request<undefined>(one(target, event.scope, event.name), { method: "DELETE" }),
  );
}
