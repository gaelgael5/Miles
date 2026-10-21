import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type ModelProblem,
  type SavedVersion,
  useRestoreVersion,
  useSaveVersion,
  useVersions,
} from "../api/dataModels";
import { ApiError } from "../api/http";
import { ConfirmDialog } from "../layout/ConfirmDialog";

type Detail = {
  code?: string;
  field?: string;
  reason?: string;
  reports?: { path: string; problems: ModelProblem[] }[];
};

function VersionRefusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const detail =
    error instanceof ApiError && typeof error.detail === "object" ? (error.detail as Detail) : null;
  let message = t("versions.errors.unexpected");
  if (detail?.code === "parametrage_invalide") {
    message = t("versions.errors.invalid");
  } else if (detail?.code === "acces_depot") {
    message = t("dataModels.errors.access", { reason: detail.reason ?? "echec" });
  } else if (detail?.field === "label") {
    message = t("versions.errors.label");
  } else if (error instanceof ApiError && typeof error.detail === "string") {
    message = t(`versions.errors.conflict.${error.detail}`, {
      defaultValue: t(`dataModels.errors.conflict.${error.detail}`),
    });
  }
  return (
    <div className="alert" role="alert">
      <p>{message}</p>
      {detail?.reports?.map((report) => (
        <div key={report.path}>
          <p className="mono">{report.path || t("versions.tree")}</p>
          <ul>
            {report.problems.map((p) => (
              <li key={`${p.path}-${p.code}`}>
                {p.path && <span className="mono">{p.path} — </span>}
                {t(`dataModels.problems.${p.code}`, { detail: p.detail ?? "" })}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function SaveForm({ workspaceId, onDone }: { workspaceId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const save = useSaveVersion(workspaceId);
  const [label, setLabel] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate(label, { onSuccess: onDone });
  }

  return (
    <form className="panel" onSubmit={submit} aria-label={t("versions.save")}>
      <label className="field">
        {t("versions.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <p className="help">{t("versions.labelHelp")}</p>
      {save.isError && <VersionRefusal error={save.error} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={save.isPending}>
          {t("versions.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDone}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function VersionRow({ workspaceId, version }: { workspaceId: string; version: SavedVersion }) {
  const { t, i18n } = useTranslation();
  const restore = useRestoreVersion(workspaceId);
  const [confirming, setConfirming] = useState(false);
  const date = new Date(version.saved_at).toLocaleString(i18n.language);

  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">
          {t("versions.number", { number: version.number })} — {version.label}
        </div>
        <div className="row-sub">
          {date} · {version.author} · <span className="mono">{version.commit.slice(0, 10)}</span>
        </div>
      </div>
      <div className="actions row-actions">
        <button type="button" className="btn btn-secondary" onClick={() => setConfirming(true)}>
          {t("versions.restore")}
        </button>
      </div>
      {restore.isSuccess && (
        <p className="notice row-detail" role="status">
          {t("versions.restored", { commit: restore.data.commit.slice(0, 10) })}
        </p>
      )}
      {restore.isError && (
        <div className="row-detail">
          <VersionRefusal error={restore.error} />
        </div>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("versions.restoreConfirm.title", { number: version.number })}
          confirmLabel={t("versions.restoreConfirm.confirm")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            restore.mutate(version.number);
          }}
        >
          <p>{t("versions.restoreConfirm.body", { label: version.label })}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

/** Versions de la branche de travail : enregistrées explicitement, jamais automatiquement. */
export function VersionsPanel({ workspaceId }: { workspaceId: string }) {
  const { t } = useTranslation();
  const versions = useVersions(workspaceId);
  const [saving, setSaving] = useState(false);

  return (
    <section className="card" aria-labelledby="versions-title">
      <div className="card-head">
        <h2 id="versions-title">{t("versions.title")}</h2>
        {!saving && (
          <button type="button" className="btn btn-primary" onClick={() => setSaving(true)}>
            {t("versions.save")}
          </button>
        )}
      </div>
      {saving && <SaveForm workspaceId={workspaceId} onDone={() => setSaving(false)} />}
      {versions.isError && <VersionRefusal error={versions.error} />}
      {versions.isSuccess && versions.data.length === 0 && (
        <p className="muted">{t("versions.empty")}</p>
      )}
      {versions.isSuccess && versions.data.length > 0 && (
        <ul className="plain-list">
          {versions.data.map((v) => (
            <VersionRow key={v.number} workspaceId={workspaceId} version={v} />
          ))}
        </ul>
      )}
    </section>
  );
}
