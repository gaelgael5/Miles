import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { proposeDslName } from "../api/contracts";
import { SHARED_SCOPE } from "../api/dataModels";
import { useDomains } from "../api/domains";
import type { WorkTarget } from "../api/workTarget";
import {
  type Declaration,
  type EventType,
  useDeclareEventType,
  useEventPerimeters,
  useEventSocle,
  useReplaceEventType,
} from "../api/workflowEvents";
import { socleNames } from "../workspaces/EventSocle";
import { ModelRefusal } from "../workspaces/ModelRefusal";
import { BASE, ParentSelect, eligibleParents, parentPair } from "./Inheritance";

/**
 * La SAISIE d'une déclaration : créer, et modifier ce qui n'est pas le nom.
 *
 * Sortie de `EventsScreen` le 17/11/2026 (story `8a9ff6bc`) : l'écran s'est mis à porter
 * l'arbre des périmètres, et les deux ensemble dépassaient de moitié la limite de 300
 * lignes du dépôt.
 *
 * Depuis le 19/11/2026, on ne CHOISIT plus un modèle (Gael : « on créé un model puis on le
 * selectionne dans event. ca pose un probleme de fond ») : on crée l'event, son payload
 * est créé avec lui, et il hérite d'un parent — l'event de base par défaut. Le `<select>`
 * des modèles a donc disparu de cet écran ; le payload s'édite par l'écran des modèles,
 * qu'on ouvre depuis la ligne du type.
 */
const REFUSED_FIELDS = {
  name: "workflowEvents.errors.invalid.name",
  scope_non_ecrivable: "workflowEvents.errors.invalid.scope",
  model_non_ecrivable: "workflowEvents.errors.invalid.model",
};

/**
 * Les clefs d'unicité, saisies DANS L'ORDRE et séparées par des virgules.
 *
 * Une liste ordonnée et non des cases à cocher : le moteur dérive le hash d'anti-doublon
 * par concaténation, donc l'ordre est une donnée. Un jeu de cases ne le dirait pas, et
 * trier à l'affichage changerait l'anti-doublon d'un référentiel en service.
 */
function parseUnique(text: string): string[] {
  return text
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

/** Les clefs d'anti-doublon, et les propriétés du socle qu'elles peuvent nommer. */
function UniqueField({
  target,
  unique,
  onUnique,
}: {
  target: WorkTarget;
  unique: string;
  onUnique: (value: string) => void;
}) {
  const { t } = useTranslation();
  const socle = useEventSocle(target);
  const base = [...socleNames(socle.data)].sort().join(", ");

  return (
    <>
      <label className="field">
        {t("workflowEvents.fields.unique")}
        <input className="mono" value={unique} onChange={(e) => onUnique(e.target.value)} />
      </label>
      <p className="help">{t("workflowEvents.form.uniqueHelp", { base })}</p>
    </>
  );
}

/** Les types de la branche, à plat : la liste des parents possibles vient de là. */
function useAllTypes(target: WorkTarget): EventType[] {
  // MÊME clef de requête que l'arbre de l'écran : TanStack sert le cache, donc ouvrir le
  // formulaire ne reclone pas la branche.
  const perimeters = useEventPerimeters(target);
  return (perimeters.data ?? []).flatMap((perimeter) => perimeter.types);
}

/** Création d'un type d'event : son identité, l'event dont il hérite, ses clefs. */
export function DeclareForm({
  target,
  perimeter,
  onDeclared,
  onCancel,
}: {
  target: WorkTarget;
  /** Périmètre où l'on déclare quand l'écran en montre un seul ; sinon « shared ». */
  perimeter?: string;
  onDeclared: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const declare = useDeclareEventType(target);
  const [label, setLabel] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  // Le périmètre REGARDÉ par défaut : déclarer depuis l'écran d'un périmètre et devoir
  // le choisir à nouveau ferait écrire dans le mauvais artefact d'un clic distrait.
  const [scope, setScope] = useState(perimeter ?? SHARED_SCOPE);
  const [parent, setParent] = useState(BASE);
  const [unique, setUnique] = useState("");
  const domains = useDomains(target);
  const types = useAllTypes(target);
  const shownSlug = slugTouched ? slug : proposeDslName(label);
  const pair = parentPair(parent);

  function submit(event: FormEvent) {
    event.preventDefault();
    const body: Declaration = {
      scope,
      label,
      slug: shownSlug,
      unique: parseUnique(unique),
      ...(pair === undefined ? {} : { parent_scope: pair.scope, parent_name: pair.name }),
    };
    declare.mutate(body, { onSuccess: onDeclared });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("workflowEvents.form.title")}>
      <h2>{t("workflowEvents.form.title")}</h2>
      <label className="field">
        {t("workflowEvents.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label className="field">
        {t("workflowEvents.fields.slug")}
        <input
          required
          className="mono"
          value={shownSlug}
          onChange={(e) => {
            setSlugTouched(true);
            setSlug(e.target.value);
          }}
        />
      </label>
      <p className="help">{t("workflowEvents.form.slugHelp")}</p>
      <label className="field">
        {t("workflowEvents.fields.domain")}
        <select
          value={scope}
          onChange={(e) => {
            setScope(e.target.value);
            // Le parent retenu peut ne plus être visible du nouveau périmètre : le garder
            // ferait envoyer une création que le serveur refuse (portee_du_modele).
            setParent(BASE);
          }}
        >
          <option value={SHARED_SCOPE}>{t("dataModels.list.shared")}</option>
          {(domains.data ?? []).map((d) => (
            <option key={d.name} value={d.name}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <p className="help">{t("workflowEvents.form.domainHelp")}</p>
      <ParentSelect
        label={t("workflowEvents.fields.parent")}
        types={eligibleParents(types, scope)}
        value={parent}
        onChange={setParent}
      />
      <p className="help">{t("workflowEvents.form.parentHelp")}</p>
      <UniqueField target={target} unique={unique} onUnique={setUnique} />
      {declare.isError && <ModelRefusal error={declare.error} fields={REFUSED_FIELDS} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={declare.isPending}>
          {t("workflowEvents.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

/**
 * Modification d'un type déjà déclaré : son libellé et ses clefs.
 *
 * Ni son NOM — c'est lui qu'un script de workflow écrit —, ni son MODÈLE : le payload
 * appartient à l'event depuis le 19/11/2026, et son héritage se redirige en bas de la
 * ligne. Le modèle déjà déclaré est renvoyé tel quel, pour que la route le retrouve.
 */
export function EditForm({
  target,
  declared,
  onSaved,
  onCancel,
}: {
  target: WorkTarget;
  declared: EventType;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const replace = useReplaceEventType(target);
  const [label, setLabel] = useState(declared.label);
  const [unique, setUnique] = useState(declared.unique.join(", "));

  function submit(event: FormEvent) {
    event.preventDefault();
    replace.mutate(
      {
        scope: declared.scope,
        name: declared.name,
        label,
        model_scope: declared.model_scope,
        model_name: declared.model_name,
        unique: parseUnique(unique),
      },
      { onSuccess: onSaved },
    );
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("workflowEvents.edit.title")}>
      <h2>{t("workflowEvents.edit.title", { name: declared.name })}</h2>
      <label className="field">
        {t("workflowEvents.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <UniqueField target={target} unique={unique} onUnique={setUnique} />
      <p className="help">{t("workflowEvents.edit.nameHelp")}</p>
      {replace.isError && <ModelRefusal error={replace.error} fields={REFUSED_FIELDS} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={replace.isPending}>
          {t("workflowEvents.edit.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}
