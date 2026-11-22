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
  /**
   * Les modèles dont le payload HÉRITE (`allOf: $ref`), par leur chemin.
   *
   * Vide : l'event ne tient que du socle commun — il dérive de l'event de base, et son
   * fichier ne porte aucun renvoi, le moteur appliquant sa racine d'office.
   *
   * Le CHEMIN, pour qu'il se compare au `model` des autres types : c'est ainsi que
   * l'écran dit de quel event l'héritage vient, sans recomposer de clef.
   */
  parents: string[];
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

/**
 * Ce qu'une création porte, côté saisie : l'identité, le PARENT, les clefs.
 *
 * Plus de modèle à choisir depuis le 19/11/2026 (Gael : « dans le menu types d'events ce
 * que l'on fait c'est ajouter et créer les events ») : le payload est créé avec l'event,
 * et il hérite du parent désigné. Sans parent, c'est l'event de base.
 *
 * La route accepte aussi un modèle existant — c'est le geste d'un agent, qui a écrit son
 * modèle d'abord. L'écran, lui, ne l'offre plus.
 */
export interface Declaration {
  scope: string;
  label: string;
  slug: string;
  parent_scope?: string;
  parent_name?: string;
  unique: string[];
}

/**
 * Ce qu'une REDÉCLARATION porte : le libellé, les clefs, et le modèle déjà déclaré.
 *
 * Le modèle est renvoyé tel quel et ne s'édite plus depuis cet écran : le payload
 * appartient à l'event depuis le 19/11/2026, et son héritage se redirige à part.
 */
export interface Redeclaration {
  scope: string;
  name: string;
  label: string;
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

/** Un manquement de l'artefact, positionné comme le MOTEUR le positionne. */
export interface DslProblem {
  line: number;
  column: number;
  message: string;
}

/**
 * Un périmètre et son artefact : ses types, ou ce qui empêche de les relire.
 *
 * La lecture est par PÉRIMÈTRE et non en liste plate (story 8a9ff6bc) : le bloc Events se
 * déplie périmètre par périmètre, un périmètre sans aucun type doit s'y voir pour qu'on
 * puisse y déclarer le premier, et un artefact retouché hors de Miles ne doit arrêter que
 * le sien. La surface MCP, elle, garde la liste plate en tout-ou-rien : un agent écrit, et
 * une liste amputée l'amènerait à déclarer par-dessus ce qu'on n'a pas su relire.
 */
export interface EventPerimeter {
  /** « shared », ou le nom du domaine. */
  scope: string;
  /** Le fichier de l'artefact, qu'il existe ou non : celui qu'on nomme quand il est cassé. */
  path: string;
  types: EventType[];
  /** Non vide : `types` est vide, et ce n'est PAS « aucun type ». Deux états distincts. */
  problems: DslProblem[];
}

/** `enabled` à false pour le menu replié : chaque lecture de branche la clone. */
export function useEventPerimeters(target: WorkTarget, enabled = true) {
  return useQuery({
    queryKey: key(target),
    enabled,
    queryFn: ({ signal }) => request<EventPerimeter[]>(root(target), { signal }),
  });
}

/**
 * Le socle commun des types d'event, SERVI par le portail.
 *
 * Clef de requête à part de celle des déclarations : il vient du moteur installé, pas de
 * la branche — déclarer un type ne le change pas, et il n'a pas à être relu.
 */
export function useEventSocle(target: WorkTarget, enabled = true) {
  return useQuery({
    queryKey: ["workflow-event-socle"],
    enabled,
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
  return useInvalidating(target, (input: Redeclaration) =>
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

/**
 * Redirige l'héritage d'un type d'event ; `undefined` le ramène à l'event de base.
 *
 * « cet heritage peut être redirigé sur un autre event présent sur le disque » (Gael,
 * 19/11/2026). Ce qui change est UNE ligne du modèle du payload, son `allOf: $ref` —
 * l'artefact du périmètre ne bouge pas, d'où une route à part de la redéclaration.
 */
export function useRedirectInheritance(target: WorkTarget) {
  return useInvalidating(
    target,
    (input: { scope: string; name: string; parent: { scope: string; name: string } | undefined }) =>
      request<EventType>(atBranch(target, "workflow-events", input.scope, input.name, "parent"), {
        method: "PUT",
        body: JSON.stringify(
          input.parent === undefined
            ? {}
            : { parent_scope: input.parent.scope, parent_name: input.parent.name },
        ),
      }),
  );
}

export function useDeleteEventType(target: WorkTarget) {
  return useInvalidating(target, (declared: EventType) =>
    request<undefined>(one(target, declared.scope, declared.name), { method: "DELETE" }),
  );
}
