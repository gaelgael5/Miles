import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import { proposeSlug } from "../api/contracts";
import { SHARED_SCOPE, useDataModels } from "../api/dataModels";
import { useDomains } from "../api/domains";
import type { WorkTarget } from "../api/workTarget";
import {
  type Declaration,
  type EventType,
  useDeclareEventType,
  useDeleteEventType,
  useEventSocle,
  useEventTypes,
  useReplaceEventType,
} from "../api/workflowEvents";
import type { Workspace } from "../api/workspaces";
import { DomainForm } from "./DomainForm";
import { socleNames } from "./EventSocle";
import { ModelRefusal } from "./ModelRefusal";

// Le nom d'un type d'event est plus étroit que celui d'un modèle : le DSL du moteur refuse
// le tiret (mesuré le 11/11/2026). La proposition faite d'après le libellé doit donc le
// remplacer, sinon « Demande soumise » proposerait « demande-soumise », aussitôt refusé
// par le serveur — un aller-retour pour une règle que l'écran connaît déjà.
function proposeEventName(label: string): string {
  return proposeSlug(label).replaceAll("-", "_");
}

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
function DeclareForm({
  target,
  onDeclared,
  onCancel,
}: {
  target: WorkTarget;
  onDeclared: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const declare = useDeclareEventType(target);
  const [label, setLabel] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [scope, setScope] = useState(SHARED_SCOPE);
  const [model, setModel] = useState("");
  const [unique, setUnique] = useState("");
  const domains = useDomains(target);
  const shownSlug = slugTouched ? slug : proposeEventName(label);

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
function EditForm({
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

function EventRow({
  target,
  declared,
  onOpenModel,
}: {
  target: WorkTarget;
  declared: EventType;
  onOpenModel: () => void;
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const [editing, setEditing] = useState(false);
  const remove = useDeleteEventType(target);

  return (
    <li className="row row-openable">
      <div className="row-main">
        <div className="row-title">{declared.label}</div>
        {/* Le nom du DSL, pas le libellé : c'est lui qu'on écrit dans un `DEFINE EVENT`,
            et la seule chose qu'un script de workflow connaisse de cet écran. */}
        <div className="row-sub mono">{declared.name}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("workflowEvents.list.model")}</div>
        {/* Le modèle est un modèle ORDINAIRE depuis le 14/11/2026 : il s'édite par l'écran
            des modèles, et non par un éditeur propre aux events qui n'existe plus. */}
        <button type="button" className="value row-open" onClick={onOpenModel}>
          <span className="mono">{declared.model}</span>
        </button>
      </div>
      <div className="cell">
        <div className="caption">{t("workflowEvents.list.unique")}</div>
        <div className="value mono">
          {declared.unique.length > 0 ? declared.unique.join(", ") : t("workflowEvents.list.noDedup")}
        </div>
      </div>
      {/* Une déclaration dont le modèle a disparu bloque l'enregistrement d'une version :
          le dire ICI, c'est le dire là où on peut la corriger. */}
      {declared.model_missing && (
        <span className="badge badge-danger">{t("workflowEvents.list.modelMissing")}</span>
      )}
      <div className="actions row-actions">
        {!target.readOnly && (
          <>
            <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)}>
              {t("workflowEvents.list.edit")}
            </button>
            <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
              {t("dataModels.list.delete")}
            </button>
          </>
        )}
      </div>
      {editing && (
        <div className="row-detail">
          <EditForm
            target={target}
            declared={declared}
            onSaved={() => setEditing(false)}
            onCancel={() => setEditing(false)}
          />
        </div>
      )}
      {remove.isError && (
        <div className="row-detail">
          <ModelRefusal error={remove.error} />
        </div>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("workflowEvents.deleteConfirm.title")}
          confirmLabel={t("dataModels.deleteConfirm.confirm")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate(declared);
          }}
        >
          <p>{t("workflowEvents.deleteConfirm.body", { name: declared.name })}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

/**
 * Référentiel des types d'event du workspace.
 *
 * Ce que cet écran produit, c'est le `DEFINE EVENT … AS @modele` de l'artefact d'un
 * périmètre — et non plus un document de schéma : depuis le 14/11/2026, le payload d'un
 * type d'event est un modèle de données ordinaire, qui s'édite par l'écran des modèles.
 */
export function EventsScreen({
  workspace,
  target,
  onBack,
  onOpenModel,
}: {
  workspace: Workspace;
  target: WorkTarget;
  onBack: () => void;
  onOpenModel: (declared: EventType) => void;
}) {
  const { t } = useTranslation();
  const types = useEventTypes(target);
  const [creating, setCreating] = useState(false);
  const [addingDomain, setAddingDomain] = useState(false);
  const [added, setAdded] = useState<string | null>(null);

  return (
    <section aria-labelledby="workflow-events-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="workflow-events-title">{t("workflowEvents.title", { name: workspace.name })}</h1>
          <p className="lead">
            {t("workflowEvents.intro")} <span className="mono">{workspace.work_branch}</span>
          </p>
        </div>
        {!target.readOnly && (
          <div className="actions">
            {!addingDomain && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setAdded(null);
                  setAddingDomain(true);
                }}
              >
                {t("dataModels.addDomain")}
              </button>
            )}
            {!creating && (
              <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
                {t("workflowEvents.add")}
              </button>
            )}
          </div>
        )}
      </div>
      {addingDomain && (
        <DomainForm
          target={target}
          onAdded={(domain) => {
            setAddingDomain(false);
            setAdded(domain.name);
          }}
          onCancel={() => setAddingDomain(false)}
        />
      )}
      {added !== null && (
        <p className="notice" role="status">
          {t("dataModels.domainForm.added", { name: added })}
        </p>
      )}
      {creating && (
        <DeclareForm
          target={target}
          onDeclared={() => setCreating(false)}
          onCancel={() => setCreating(false)}
        />
      )}
      {types.isPending && (
        <p className="muted" role="status">
          {t("dataModels.loading")}
        </p>
      )}
      {types.isError && <ModelRefusal error={types.error} />}
      {types.isSuccess && types.data.length === 0 && (
        <p className="muted">{t("workflowEvents.empty")}</p>
      )}
      {types.isSuccess && types.data.length > 0 && (
        <ul className="card-list plain-list">
          {types.data.map((d) => (
            <EventRow
              key={`${d.scope}/${d.name}`}
              target={target}
              declared={d}
              onOpenModel={() => onOpenModel(d)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
