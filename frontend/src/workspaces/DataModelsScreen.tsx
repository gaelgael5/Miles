import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type DataModel,
  type ModelProblem,
  SHARED_SCOPE,
  useCreateDataModel,
  useDataModel,
  useDataModels,
  useDeleteDataModel,
} from "../api/dataModels";
import { ApiError } from "../api/http";
import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";
import { ConfirmDialog } from "../layout/ConfirmDialog";

type Detail = {
  code?: string;
  field?: string;
  reason?: string;
  line?: number | null;
  column?: number | null;
  message?: string;
  problems?: ModelProblem[];
  by?: string[];
};

function detailOf(error: unknown): Detail | null {
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail !== null) {
    return error.detail as Detail;
  }
  return null;
}

/** Message d'un refus ; les manquements à la grammaire s'affichent à part, un par ligne. */
function errorKey(error: unknown): [string, Record<string, string>] {
  const detail = detailOf(error);
  if (detail?.code === "yaml_invalide") {
    const at = { line: String(detail.line ?? "?"), column: String(detail.column ?? "?") };
    return ["dataModels.errors.syntax", { ...at, message: detail.message ?? "" }];
  }
  if (detail?.code === "modele_non_conforme") {
    return ["dataModels.errors.grammar", {}];
  }
  if (detail?.code === "utilise") {
    return ["dataModels.errors.inUse", { list: (detail.by ?? []).join(", ") }];
  }
  if (detail?.code === "acces_depot") {
    return ["dataModels.errors.access", { reason: detail.reason ?? "echec" }];
  }
  if (detail?.field) {
    return [`dataModels.errors.invalid.${detail.field}`, {}];
  }
  if (error instanceof ApiError && typeof error.detail === "string") {
    return [`dataModels.errors.conflict.${error.detail}`, {}];
  }
  return ["dataModels.errors.unexpected", {}];
}

function Refusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const [key, values] = errorKey(error);
  const problems = detailOf(error)?.problems ?? [];
  return (
    <div className="alert" role="alert">
      <p>{t(key, values)}</p>
      {problems.length > 0 && (
        <ul>
          {problems.map((p) => (
            <li key={`${p.path}-${p.code}`}>
              <span className="mono">{p.path || "/"}</span> —{" "}
              {t(`dataModels.problems.${p.code}`, { detail: p.detail ?? "" })}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CreateForm({ target, onDone }: { target: WorkTarget; onDone: () => void }) {
  const { t } = useTranslation();
  const create = useCreateDataModel(target);
  const [domain, setDomain] = useState("");
  const [content, setContent] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    // Domaine vide : transverse. On ne promeut au transverse qu'au second usage réel.
    create.mutate({ scope: domain.trim() || SHARED_SCOPE, content }, { onSuccess: onDone });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("dataModels.form.title")}>
      <h2>{t("dataModels.form.title")}</h2>
      <label className="field">
        {t("dataModels.fields.domain")}
        <input value={domain} onChange={(e) => setDomain(e.target.value)} />
      </label>
      <p className="help">{t("dataModels.form.domainHelp")}</p>
      <label className="field">
        {t("dataModels.fields.content")}
        <textarea
          required
          rows={16}
          spellCheck={false}
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
      </label>
      {create.isError && <Refusal error={create.error} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={create.isPending}>
          {t("dataModels.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDone}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function ModelRow({ target, model }: { target: WorkTarget; model: DataModel }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const read = useDataModel(target, open ? model : null);
  const remove = useDeleteDataModel(target);

  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{model.name}</div>
        <div className="row-sub mono">{model.path}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("dataModels.list.captionScope")}</div>
        <div className="value">
          {model.scope === SHARED_SCOPE ? t("dataModels.list.shared") : model.scope}
        </div>
      </div>
      <div className="actions row-actions">
        <button
          type="button"
          className="btn btn-secondary"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {t(open ? "dataModels.list.hide" : "dataModels.list.show")}
        </button>
        {!target.readOnly && (
          <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
            {t("dataModels.list.delete")}
          </button>
        )}
      </div>
      {open && read.data && (
        <pre className="row-detail code-block" aria-label={model.path}>
          {read.data.content}
        </pre>
      )}
      {read.isError && (
        <div className="row-detail">
          <Refusal error={read.error} />
        </div>
      )}
      {remove.isError && (
        <div className="row-detail">
          <Refusal error={remove.error} />
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
}: {
  workspace: Workspace;
  target: WorkTarget;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const models = useDataModels(target);
  const [creating, setCreating] = useState(false);

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
        {!creating && !target.readOnly && (
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            {t("dataModels.add")}
          </button>
        )}
      </div>
      {/* En haut de l'atelier, comme sur toutes ses maquettes : figer ce qu'on vient d'écrire. */}
      {creating && <CreateForm target={target} onDone={() => setCreating(false)} />}
      {models.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {models.isError && <Refusal error={models.error} />}
      {models.isSuccess && models.data.length === 0 && (
        <p className="muted">{t("dataModels.empty")}</p>
      )}
      {models.isSuccess && models.data.length > 0 && (
        <ul className="card-list plain-list">
          {models.data.map((m) => (
            <ModelRow key={m.path} target={target} model={m} />
          ))}
        </ul>
      )}
    </section>
  );
}
