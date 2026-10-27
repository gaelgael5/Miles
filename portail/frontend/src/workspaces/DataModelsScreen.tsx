import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { proposeSlug } from "../api/contracts";
import {
  type DataModel,
  SHARED_SCOPE,
  useDataModels,
  useDeclareDataModel,
  useDeleteDataModel,
} from "../api/dataModels";
import { useDomains } from "../api/domains";
import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";
import { ConfirmDialog } from "../layout/ConfirmDialog";
import { DomainForm } from "./DomainForm";
import { ModelRefusal } from "./ModelRefusal";

/**
 * Création en deux temps (Gael, 23/10/2026) : label, slug et domaine ici ; le YAML
 * s'écrit ensuite sur l'écran d'édition du modèle, qu'on ouvre aussitôt.
 */
function CreateForm({
  target,
  onCreated,
  onCancel,
}: {
  target: WorkTarget;
  onCreated: (model: DataModel) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const declare = useDeclareDataModel(target);
  const [label, setLabel] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  // Transverse par défaut : on ne promeut au transverse qu'au second usage réel, mais un
  // domaine se choisit dans la liste, jamais ne se tape (story 7fa00f56).
  const [scope, setScope] = useState(SHARED_SCOPE);
  const domains = useDomains(target);
  const shownSlug = slugTouched ? slug : proposeSlug(label);

  function submit(event: FormEvent) {
    event.preventDefault();
    declare.mutate({ scope, label, slug: shownSlug }, { onSuccess: onCreated });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("dataModels.form.title")}>
      <h2>{t("dataModels.form.title")}</h2>
      <label className="field">
        {t("dataModels.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label className="field">
        {t("dataModels.fields.slug")}
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
      <p className="help">{t("dataModels.form.slugHelp")}</p>
      <label className="field">
        {t("dataModels.fields.domain")}
        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value={SHARED_SCOPE}>{t("dataModels.list.shared")}</option>
          {(domains.data ?? []).map((d) => (
            <option key={d.name} value={d.name}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <p className="help">{t("dataModels.form.domainHelp")}</p>
      {declare.isError && <ModelRefusal error={declare.error} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={declare.isPending}>
          {t("dataModels.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function ModelRow({
  target,
  model,
  onOpen,
}: {
  target: WorkTarget;
  model: DataModel;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteDataModel(target);

  return (
    <li className="row row-openable">
      <div className="row-main">
        {/* Toute la ligne ouvre le modèle (fbe9b512) : ce bouton étend sa zone à la ligne
            par CSS, plutôt qu'un <li> cliquable qui engloberait « Supprimer », mal lu au
            clavier et par un lecteur d'écran. Un modèle créé par son YAML n'a pas de label. */}
        <button type="button" className="row-title row-open" onClick={onOpen}>
          {model.label ?? model.name}
        </button>
        <div className="row-sub mono">{model.path}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("dataModels.list.captionScope")}</div>
        <div className="value">
          {model.scope === SHARED_SCOPE ? t("dataModels.list.shared") : model.scope}
        </div>
      </div>
      <div className="actions row-actions">
        {!target.readOnly && (
          <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
            {t("dataModels.list.delete")}
          </button>
        )}
      </div>
      {remove.isError && (
        <div className="row-detail">
          <ModelRefusal error={remove.error} />
        </div>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("dataModels.deleteConfirm.title")}
          confirmLabel={t("dataModels.deleteConfirm.confirm")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate(model);
          }}
        >
          <p>{t("dataModels.deleteConfirm.body", { path: model.path })}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

/** Modèles de données du workspace, lus et écrits dans sa branche de travail. */
export function DataModelsScreen({
  workspace,
  target,
  onBack,
  onOpen,
}: {
  workspace: Workspace;
  target: WorkTarget;
  onBack: () => void;
  onOpen: (model: DataModel) => void;
}) {
  const { t } = useTranslation();
  const models = useDataModels(target);
  const [creating, setCreating] = useState(false);
  const [addingDomain, setAddingDomain] = useState(false);
  const [added, setAdded] = useState<string | null>(null);

  return (
    <section aria-labelledby="data-models-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="data-models-title">{t("dataModels.title", { name: workspace.name })}</h1>
          <p className="lead">
            {t("dataModels.intro")} <span className="mono">{workspace.work_branch}</span>
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
                {t("dataModels.add")}
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
        <CreateForm target={target} onCreated={onOpen} onCancel={() => setCreating(false)} />
      )}
      {models.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {models.isError && <ModelRefusal error={models.error} />}
      {models.isSuccess && models.data.length === 0 && (
        <p className="muted">{t("dataModels.empty")}</p>
      )}
      {models.isSuccess && models.data.length > 0 && (
        <ul className="card-list plain-list">
          {models.data.map((m) => (
            <ModelRow key={m.path} target={target} model={m} onOpen={() => onOpen(m)} />
          ))}
        </ul>
      )}
    </section>
  );
}
