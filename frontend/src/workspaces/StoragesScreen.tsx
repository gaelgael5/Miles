import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/http";
import { storageProblems, useSaveStorage, useStorages } from "../api/storages";
import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";
import { EMPTY_STORAGE, StorageForm } from "./StorageForm";

/** Message d'un échec qui n'est pas un refus détaillé : nom pris, accès au dépôt… */
export function storageErrorKey(error: unknown): string {
  if (error instanceof ApiError && error.status === 409 && typeof error.detail === "string") {
    return `storages.errors.${error.detail}`;
  }
  return "storages.errors.unexpected";
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
  const save = useSaveStorage(target);
  const problems = storageProblems(save.error);
  return (
    <>
      <h2>{t("storages.form.title")}</h2>
      <StorageForm
        target={target}
        initial={EMPTY_STORAGE}
        creating
        problems={problems}
        pending={save.isPending}
        submitLabel={t("storages.form.submit")}
        onSubmit={(storage) =>
          save.mutate(storage, { onSuccess: (saved) => onCreated(saved.name) })
        }
      >
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t("dataModels.form.cancel")}
        </button>
      </StorageForm>
      {save.isError && problems.length === 0 && (
        <p className="alert" role="alert">
          {t(storageErrorKey(save.error))}
        </p>
      )}
    </>
  );
}

/**
 * Storages de la branche (story 844f15ad) : les collections d'objets JSON stockées en
 * base. Ce qui est stocké se déclare ici ; comment on le remplit, dans « Sources ».
 */
export function StoragesScreen({
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
  const storages = useStorages(target);
  const [creating, setCreating] = useState(false);

  return (
    <section aria-labelledby="storages-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="storages-title">{t("storages.title", { name: workspace.name })}</h1>
          <p className="lead">{t("storages.intro")}</p>
        </div>
        {!creating && !target.readOnly && (
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            {t("storages.add")}
          </button>
        )}
      </div>
      {creating && (
        <CreateForm target={target} onCreated={onOpen} onCancel={() => setCreating(false)} />
      )}
      {storages.isPending && (
        <p className="muted" role="status">
          {t("dataModels.loading")}
        </p>
      )}
      {storages.isError && (
        <p className="alert" role="alert">
          {t("storages.errors.unexpected")}
        </p>
      )}
      {storages.isSuccess && storages.data.length === 0 && (
        <p className="muted">{t("storages.empty")}</p>
      )}
      {storages.isSuccess && storages.data.length > 0 && (
        <ul className="card-list plain-list">
          {storages.data.map((s) => (
            <li key={s.name} className="row">
              <div className="row-main">
                <div className="row-title">{s.name}</div>
                <div className="row-sub mono">storages/{s.name}.yaml</div>
              </div>
              <div className="cell">
                <div className="caption">{t("storages.fields.model")}</div>
                <div className="value">{s.model ?? t("storages.unreadable")}</div>
              </div>
              <div className="cell">
                <div className="caption">{t("storages.fields.keys")}</div>
                <div className="value mono">{s.keys?.join(", ") ?? "—"}</div>
              </div>
              <div className="actions row-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => onOpen(s.name)}
                >
                  {t("contracts.list.open")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
