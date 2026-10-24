import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/http";
import { sourceProblems, useSaveSource, useSources } from "../api/sources";
import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";
import { EMPTY_SOURCE, SourceForm } from "./SourceForm";

/** Message d'un échec qui n'est pas un refus détaillé : nom pris, accès au dépôt… */
export function sourceErrorKey(error: unknown): string {
  if (error instanceof ApiError && error.status === 409 && typeof error.detail === "string") {
    return `sources.errors.${error.detail}`;
  }
  return "sources.errors.unexpected";
}

function CreateForm({
  target,
  onCreated,
  onCancel,
}: {
  target: WorkTarget;
  onCreated: (name: string) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const save = useSaveSource(target);
  const problems = sourceProblems(save.error);
  return (
    <>
      <h2>{t("sources.form.title")}</h2>
      <SourceForm
        target={target}
        initial={EMPTY_SOURCE}
        creating
        problems={problems}
        pending={save.isPending}
        submitLabel={t("sources.form.submit")}
        onSubmit={(source) => save.mutate(source, { onSuccess: (saved) => onCreated(saved.name) })}
      >
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t("dataModels.form.cancel")}
        </button>
      </SourceForm>
      {save.isError && problems.length === 0 && (
        <p className="alert" role="alert">{t(sourceErrorKey(save.error))}</p>
      )}
    </>
  );
}

/**
 * Sources de données de la branche (story 66391afe) : COMMENT on remplit un storage.
 * Ce qui est stocké — modèle, clé, propriétés indexables — se déclare dans « Storages ».
 */
export function SourcesScreen({
  workspace,
  target,
  onBack,
  onOpen,
}: {
  workspace: Workspace;
  target: WorkTarget;
  onBack: () => void;
  onOpen: (name: string) => void;
}) {
  const { t } = useTranslation();
  const sources = useSources(target);
  const [creating, setCreating] = useState(false);

  return (
    <section aria-labelledby="sources-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="sources-title">{t("sources.title", { name: workspace.name })}</h1>
          <p className="lead">{t("sources.intro")}</p>
        </div>
        {!creating && !target.readOnly && (
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            {t("sources.add")}
          </button>
        )}
      </div>
      {creating && <CreateForm target={target} onCreated={onOpen} onCancel={() => setCreating(false)} />}
      {sources.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {sources.isError && <p className="alert" role="alert">{t("sources.errors.unexpected")}</p>}
      {sources.isSuccess && sources.data.length === 0 && <p className="muted">{t("sources.empty")}</p>}
      {sources.isSuccess && sources.data.length > 0 && (
        <ul className="card-list plain-list">
          {sources.data.map((s) => (
            <li key={s.name} className="row row-openable">
              <div className="row-main">
                {/* Toute la ligne ouvre la source (fbe9b512) : le bouton du titre la couvre. */}
                <button type="button" className="row-title row-open" onClick={() => onOpen(s.name)}>
                  {s.label ?? s.name}
                </button>
                <div className="row-sub mono">sources/{s.name}.yaml</div>
              </div>
              <div className="cell">
                <div className="caption">{t("sources.fields.storage")}</div>
                <div className="value">{s.storage ?? t("sources.unreadable")}</div>
              </div>
              <div className="cell">
                <div className="caption">{t("sources.fields.chain")}</div>
                <div className="value mono">{s.chain ?? "—"}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
