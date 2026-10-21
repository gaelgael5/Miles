import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/http";
import { type TreeDiagnosis, type Workspace, useOpenWorkBranch } from "../api/workspaces";

function diagnosisOf(error: unknown): TreeDiagnosis | null {
  if (error instanceof ApiError && error.status === 422) {
    const detail = error.detail as TreeDiagnosis | undefined;
    return detail?.code === "arborescence_non_conforme" ? detail : null;
  }
  return null;
}

function errorKey(error: unknown): string {
  if (diagnosisOf(error) !== null) {
    return "workspaces.work.nonConform";
  }
  if (error instanceof ApiError && error.status === 409) {
    return `workspaces.work.conflict.${String(error.detail)}`;
  }
  if (error instanceof ApiError && error.status === 422) {
    const detail = error.detail as { code?: string; reason?: string } | undefined;
    if (detail?.code === "acces_depot") {
      return `workspaces.work.access.${detail.reason ?? "echec"}`;
    }
  }
  return "workspaces.errors.unexpected";
}

/** Branche de travail : l'espace où l'on fabrique le paramétrage, une par workspace. */
export function WorkBranchPanel({ workspace }: { workspace: Workspace }) {
  const { t } = useTranslation();
  const open = useOpenWorkBranch(workspace.id);
  const [name, setName] = useState("atelier");
  const diagnosis = diagnosisOf(open.error);

  if (workspace.work_branch !== null) {
    return <p>{t("workspaces.work.current", { branch: workspace.work_branch })}</p>;
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    open.mutate(name);
  }

  return (
    <form onSubmit={submit} aria-label={t("workspaces.work.title")}>
      <p>{t("workspaces.work.none")}</p>
      <label>
        {t("workspaces.work.name")}
        <input required value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <button type="submit" disabled={open.isPending}>
        {t("workspaces.work.open")}
      </button>
      {open.data?.outcome && <p role="status">{t(`workspaces.work.outcome.${open.data.outcome}`)}</p>}
      {open.isError && <p role="alert">{t(errorKey(open.error))}</p>}
      {diagnosis && (
        <ul>
          {diagnosis.manifest !== "valide" && (
            <li>{t(`workspaces.work.manifest.${diagnosis.manifest}`)}</li>
          )}
          {diagnosis.environment_dirs.map((dir) => (
            <li key={dir}>{t("workspaces.work.environmentDir", { dir })}</li>
          ))}
          {diagnosis.unexpected.map((path) => (
            <li key={path}>{t("workspaces.work.unexpected", { path })}</li>
          ))}
        </ul>
      )}
    </form>
  );
}
