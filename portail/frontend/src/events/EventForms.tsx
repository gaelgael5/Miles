import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { proposeDslName } from "../api/contracts";
import { SHARED_SCOPE, useDataModels } from "../api/dataModels";
import { useDomains } from "../api/domains";
import type { WorkTarget } from "../api/workTarget";
import {
  type Declaration,
  type EventType,
  useDeclareEventType,
  useEventSocle,
  useReplaceEventType,
} from "../api/workflowEvents";
import { socleNames } from "../workspaces/EventSocle";
import { ModelRefusal } from "../workspaces/ModelRefusal";

/**
 * La SAISIE d'une déclaration : déclarer, et modifier ce qui n'est pas le nom.
 *
 * Sortie de `EventsScreen` le 17/11/2026 (story `8a9ff6bc`) : l'écran s'est mis à porter
 * l'arbre des périmètres, et les deux ensemble dépassaient de moitié la limite de 300
 * lignes du dépôt. Les formulaires n'ont pas changé en déménageant.
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

/** Ce que portent les deux formulaires : le modèle du payload et les clefs d'unicité. */
function PayloadFields({
  target,
  scope,
  model,
  unique,
  onModel,
  onUnique,
}: {
  target: WorkTarget;
  scope: string;
  model: string;
  unique: string;
  onModel: (value: string) => void;
  onUnique: (value: string) => void;
}) {
  const { t } = useTranslation();
  const models = useDataModels(target);
  const socle = useEventSocle(target);
  // Un périmètre de domaine voit son domaine et les transverses ; un transverse, les
  // seuls transverses. Même règle que les modèles entre eux, et le serveur la retient
  // aussi — ici, c'est pour ne pas proposer ce qui serait refusé.
  const visible = (models.data ?? []).filter(
    (m) => m.scope === SHARED_SCOPE || (scope !== SHARED_SCOPE && m.scope === scope),
  );
  const base = [...socleNames(socle.data)].sort().join(", ");

  return (
    <>
      <label className="field">
        {t("workflowEvents.fields.model")}
        <select required value={model} onChange={(e) => onModel(e.target.value)}>
          <option value="">{t("workflowEvents.form.modelNone")}</option>
          {visible.map((m) => (
            <option key={m.path} value={`${m.scope}/${m.name}`}>
              {m.label ?? m.name} — {m.path}
            </option>
          ))}
        </select>
      </label>
      <p className="help">{t("workflowEvents.form.modelHelp")}</p>
      <label className="field">
        {t("workflowEvents.fields.unique")}
        <input className="mono" value={unique} onChange={(e) => onUnique(e.target.value)} />
      </label>
      <p className="help">{t("workflowEvents.form.uniqueHelp", { base })}</p>
    </>
  );
}

/** Déclaration d'un type d'event : son identité, le modèle de son payload, ses clefs. */
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
  const [model, setModel] = useState("");
  const [unique, setUnique] = useState("");
  const domains = useDomains(target);
  const shownSlug = slugTouched ? slug : proposeDslName(label);

  function submit(event: FormEvent) {
    event.preventDefault();
    const [modelScope = "", modelName = ""] = model.split("/");
    const body: Declaration = {
      scope,
      label,
      slug: shownSlug,
      model_scope: modelScope,
      model_name: modelName,
      unique: parseUnique(unique),
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
            // Le modèle retenu peut ne plus être visible du nouveau périmètre : le garder
            // ferait envoyer une déclaration que le serveur refuse (portee_du_modele).
            setModel("");
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
      <PayloadFields
        target={target}
        scope={scope}
        model={model}
        unique={unique}
        onModel={setModel}
        onUnique={setUnique}
      />
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

/** Modification d'un type déjà déclaré : tout sauf son NOM, qu'un script écrit. */
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
  const [model, setModel] = useState(`${declared.model_scope}/${declared.model_name}`);
  const [unique, setUnique] = useState(declared.unique.join(", "));

  function submit(event: FormEvent) {
    event.preventDefault();
    const [modelScope = "", modelName = ""] = model.split("/");
    replace.mutate(
      {
        scope: declared.scope,
        name: declared.name,
        label,
        model_scope: modelScope,
        model_name: modelName,
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
      <PayloadFields
        target={target}
        scope={declared.scope}
        model={model}
        unique={unique}
        onModel={setModel}
        onUnique={setUnique}
      />
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
