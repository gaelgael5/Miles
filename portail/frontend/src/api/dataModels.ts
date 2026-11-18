import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { request } from "@miles/socle-web";
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

/**
 * Ce qui DÉSIGNE un modèle. C'est de là, et de nulle part ailleurs, que son rôle se lit :
 * jusqu'au 14/11/2026 le dossier le disait, et depuis que « ce qui fait d'un modèle un
 * type d'event, c'est qu'un DEFINE EVENT le nomme », plus rien ne le distingue dans la
 * liste (Gael, 16/11/2026 : « la façon d'identifier qui fait quoi m'échappe »).
 */
export interface ModelUsage {
  /** « event_type », « storage », « source », « chain_step » ou « model ». */
  kind: string;
  /** L'identifiant du désignateur : c'est par lui qu'on l'ouvre. */
  name: string;
  label: string | null;
  /** Le fichier du dépôt qui porte la déclaration. */
  path: string;
  /** L'étape d'une chaîne, le rang d'une entrée de source ; null sinon. */
  part: string | null;
}

/** Une déclaration qui désigne un modèle absent de la branche. */
export interface BrokenModelRef extends ModelUsage {
  /** « portée/nom » du modèle désigné. */
  target: string;
}

export interface ListedModel extends DataModel {
  usages: ModelUsage[];
}

/** Les modèles de la branche et, à côté, les désignations qui ne trouvent plus leur cible. */
export interface ModelListing {
  models: ListedModel[];
  broken: BrokenModelRef[];
}

/** Un manquement à la grammaire, désigné par son chemin dans le document. */
export interface ModelProblem {
  path: string;
  code: string;
  detail: string | null;
}

export const SHARED_SCOPE = "shared";

/**
 * Les deux sens du tuyau MQTT (story 31025fe6) : « inbound » = ce que le terminal envoie
 * à Miles, « outbound » = ce que Miles envoie au terminal.
 */
export type DeviceSens = "inbound" | "outbound";
export const DEVICE_SENSES: DeviceSens[] = ["inbound", "outbound"];

/**
 * La portée d'un modèle device, telle que le serveur l'attend dans l'URL et dans la
 * désignation « portée/nom ». UN seul segment, là où le DOSSIER en a deux
 * (`devices/inbound/`) : la raison est au socle (`miles_socle.parametrage.layout`), et la
 * recopier ici serait la deuxième source qui diverge. Composée, donc, jamais écrite en
 * dur dans un écran.
 */
export function deviceScope(sens: DeviceSens): string {
  return `devices-${sens}`;
}

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

/** Un chemin proposé par l'éditeur JSLT : « $.Account[0].PickupReference ». */
export interface ModelPath {
  path: string;
  type: string;
  description: string;
  /** « date-time », « uri »… quand le schéma le précise ; chaîne vide sinon. */
  format: string;
}

/** Les chemins du modèle SOURCE d'une étape, pour l'auto-complétion de l'éditeur. */
export function useModelPaths(target: WorkTarget, scope: string | null, name: string | null) {
  return useQuery({
    queryKey: [...branchKey("model-paths", target), scope, name],
    // Sans modèle source, rien à proposer : on n'interroge pas le serveur pour rien.
    enabled: scope !== null && name !== null,
    queryFn: ({ signal }) =>
      request<{ paths: ModelPath[] }>(
        atBranch(target, "data-models", scope ?? "", name ?? "", "paths"),
        { signal },
      ),
  });
}

/** Le gabarit JSON d'un modèle : sa forme, jamais une donnée réaliste. */
export function useModelExample(target: WorkTarget) {
  return useMutation({
    mutationFn: ({ scope, name }: { scope: string; name: string }) =>
      request<{ example: unknown }>(atBranch(target, "data-models", scope, name, "example"), {
        signal: undefined,
      }),
  });
}

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

function listingQuery(target: WorkTarget) {
  return {
    queryKey: key(target),
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      request<ModelListing>(root(target), { signal }),
  };
}

/** La liste et ses désignations cassées : UNE lecture de branche, un seul commit décrit. */
export function useModelListing(target: WorkTarget) {
  return useQuery(listingQuery(target));
}

/** Les seuls modèles. Même clé que `useModelListing` : les deux partagent une requête. */
export function useDataModels(target: WorkTarget) {
  return useQuery({ ...listingQuery(target), select: (listing: ModelListing) => listing.models });
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

/** Les manquements d'un fichier ; `path` vide : l'arborescence elle-même. */
export interface FileReport {
  path: string;
  problems: ModelProblem[];
}

/** Ce qui empêche d'enregistrer une version ici, ou rien. */
export interface Freezable {
  ok: boolean;
  /**
   * « publication_requise », « rien_a_figer » ou « parametrage_invalide » ; null quand
   * rien n'empêche. C'est la raison que l'enregistrement opposerait VRAIMENT, calculée
   * par le même code que lui.
   */
  reason: string | null;
  /**
   * Ce que la validation du paramétrage a trouvé, DÈS L'OUVERTURE de l'écran (Gael,
   * 01/11/2026 : « il faudrait que le message d'erreur arrive avant que j'aie envie de
   * commiter »). Rendus même quand la raison est autre : celui qui doit d'abord publier
   * a le droit de savoir que le figement échouera ensuite.
   */
  reports: FileReport[];
}

/**
 * Peut-on figer cette branche ? (Gael, 25/10/2026)
 *
 * Demandé au serveur plutôt que déduit à l'écran : les deux raisons de refus sont
 * calculées par le MÊME code que celui qui refuse l'enregistrement, et une règle
 * recopiée ici dériverait de celle qui refuse vraiment.
 */
export function useFreezable(target: WorkTarget, enabled = true) {
  return useQuery({
    queryKey: [...versionsKey(target), "freezable"],
    enabled,
    queryFn: ({ signal }) =>
      request<Freezable>(atBranch(target, "versions", "freezable"), { signal }),
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
