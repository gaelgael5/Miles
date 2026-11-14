import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "@miles/socle-web";
import type { ModelProblem } from "./dataModels";
import { type WorkTarget, atBranch, branchKey } from "./workTarget";

/**
 * Un type d'event de workflow : une DÉCLARATION, pas un document.
 *
 * Depuis le 14/11/2026, le payload d'un type d'event est un modèle de données ordinaire ;
 * ce qui en fait un type d'event, c'est qu'un `DEFINE EVENT … AS @modele` le nomme dans
 * l'artefact de son périmètre. Conséquence assumée : un storage ou une source peut
 * désormais désigner ce modèle, ce que la liste séparée interdisait.
 *
 * `workflow-events` et non `events` : `/api/events` est déjà le journal d'audit.
 */
export interface EventType {
  /** « shared » pour un périmètre transverse, sinon le nom du domaine. */
  scope: string;
  /** Le nom qu'un script de workflow écrit : minuscules, chiffres et soulignés. */
  name: string;
  label: string;
  /** Le chemin du modèle qui décrit le payload, comme partout ailleurs dans le portail. */
  model: string;
  model_scope: string;
  model_name: string;
  /**
   * Les clefs de l'anti-doublon, DANS L'ORDRE. Le moteur en dérive un hash par
   * concaténation : deux ordres donnent deux anti-doublons, donc l'écran ne trie jamais.
   */
  unique: string[];
  /** Le modèle désigné manque sur la branche : la version ne pourra pas être enregistrée. */
  model_missing: boolean;
}

/**
 * Le socle commun, en JSON Schema, tel que le moteur le porte.
 *
 * Un SCHÉMA et non une liste de noms : l'écran le montre avec ses `format`, ses
 * descriptions et ses obligatoires, qu'un aplatissement aurait perdus. C'est aussi lui
 * qui dit quelles propriétés une clef d'unicité peut nommer sans être dans le modèle.
 */
export type SocleSchema = Record<string, unknown>;

export type { ModelProblem };

/** Ce qu'une déclaration porte, côté saisie : l'identité, le modèle, les clefs. */
export interface Declaration {
  scope: string;
  label: string;
  slug: string;
  model_scope: string;
  model_name: string;
  unique: string[];
}

function root(target: WorkTarget) {
  return atBranch(target, "workflow-events");
}

function one(target: WorkTarget, scope: string, name: string) {
  return atBranch(target, "workflow-events", scope, name);
}

function key(target: WorkTarget) {
  return branchKey("workflow-events", target);
}

export function useEventTypes(target: WorkTarget) {
  return useQuery({
    queryKey: key(target),
    queryFn: ({ signal }) => request<EventType[]>(root(target), { signal }),
  });
}

/**
 * Le socle commun des types d'event, SERVI par le portail.
 *
 * Clef de requête à part de celle des déclarations : il vient du moteur installé, pas de
 * la branche — déclarer un type ne le change pas, et il n'a pas à être relu.
 */
export function useEventSocle(target: WorkTarget) {
  return useQuery({
    queryKey: ["workflow-event-socle"],
    queryFn: ({ signal }) =>
      request<SocleSchema>(atBranch(target, "workflow-events", "socle"), { signal }),
  });
}

function useInvalidating<I, O>(target: WorkTarget, mutationFn: (input: I) => Promise<O>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => client.invalidateQueries({ queryKey: key(target) }),
  });
}

/** Déclare un type d'event dans l'artefact de son périmètre. */
export function useDeclareEventType(target: WorkTarget) {
  return useInvalidating(target, (input: Declaration) =>
    request<EventType>(atBranch(target, "workflow-events", "declarations"), {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
}

/**
 * Change le libellé, le modèle ou les clefs d'un type déjà déclaré.
 *
 * Le nom ne change pas : c'est lui qu'un script de workflow écrit, et le renommer
 * casserait tout `ON EVENT` qui le nomme. Renommer, c'est déclarer puis supprimer.
 */
export function useReplaceEventType(target: WorkTarget) {
  return useInvalidating(
    target,
    (input: { scope: string; name: string } & Omit<Declaration, "scope" | "slug">) =>
      request<EventType>(one(target, input.scope, input.name), {
        method: "PUT",
        body: JSON.stringify({
          label: input.label,
          model_scope: input.model_scope,
          model_name: input.model_name,
          unique: input.unique,
        }),
      }),
  );
}

export function useDeleteEventType(target: WorkTarget) {
  return useInvalidating(target, (declared: EventType) =>
    request<undefined>(one(target, declared.scope, declared.name), { method: "DELETE" }),
  );
}
