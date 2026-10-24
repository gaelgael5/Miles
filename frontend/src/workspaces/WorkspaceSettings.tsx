import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { useConnections } from "../api/gitAccess";
import { ApiError, invalidField } from "../api/http";
import { useSecurityServices } from "../api/security";
import {
  type AccessReport,
  type Workspace,
  newVerificationSuffix,
  useRecheckWorkspace,
  useSetRepository,
  useSetSecurityService,
  verificationBranch,
} from "../api/workspaces";
import { AccessReportView } from "./AccessReportView";
import { BranchForm } from "./BranchForm";
import { HoldControl } from "./HoldControl";
import { WorkBranchPanel } from "./WorkBranchPanel";

function failedReport(error: unknown): AccessReport | null {
  if (error instanceof ApiError && error.status === 422) {
    const detail = error.detail as { code?: string; report?: AccessReport } | undefined;
    return detail?.code === "acces_insuffisant" ? (detail.report ?? null) : null;
  }
  return null;
}

function errorKey(error: unknown): string {
  const field = invalidField(error);
  if (field !== null) {
    const reason = ((error as ApiError).detail as { reason?: string }).reason;
    return reason ? `workspaces.errors.reasons.${reason}` : `workspaces.errors.invalid.${field}`;
  }
  if (error instanceof ApiError && error.status === 409) {
    return `workspaces.errors.conflict.${String(error.detail)}`;
  }
  if (failedReport(error) !== null) {
    return "workspaces.errors.accessRefused";
  }
  return "workspaces.errors.unexpected";
}

/**
 * Dépôt par une connexion git : enregistré seulement si les cinq droits passent
 * (décision du 18/10/2026, appliquée ici depuis que la création ne porte que le nom).
 */
function RepositoryCard({ workspace }: { workspace: Workspace }) {
  const { t } = useTranslation();
  const connections = useConnections();
  const save = useSetRepository(workspace.id);
  const recheck = useRecheckWorkspace(workspace.id);
  const [connectionId, setConnectionId] = useState(workspace.git_connection_id ?? "");
  const [repoUrl, setRepoUrl] = useState(workspace.repo_url ?? "");
  const [suffix, setSuffix] = useState(newVerificationSuffix);
  const connection = connections.data?.find((c) => c.id === connectionId);
  const refused = failedReport(save.error);
  const report = recheck.data ?? workspace.last_check;
  // Changer de dépôt sous une branche de travail ouverte la laisserait dans l'ancien.
  const locked = workspace.work_branch !== null;
  const testing = save.isPending || recheck.isPending;

  function submit(event: FormEvent) {
    event.preventDefault();
    // Un essai = un nom de branche : le suivant en tire un autre, pour ne jamais
    // retomber sur une branche résiduelle d'un essai précédent.
    save.mutate(
      { git_connection_id: connectionId, repo_url: repoUrl, verification_suffix: suffix },
      { onSettled: () => setSuffix(newVerificationSuffix()) },
    );
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("workspaces.settings.repoTitle")}>
      <h2>{t("workspaces.settings.repoTitle")}</h2>
      {workspace.repo_url && (
        <p className="notice" role="status">
          {t("workspaces.settings.current", {
            url: workspace.repo_url,
            connection: workspace.git_connection_id,
          })}
        </p>
      )}
      {connections.isSuccess && connections.data.length === 0 && (
        <p className="alert">{t("workspaces.settings.noConnections")}</p>
      )}
      <label className="field">
        {t("workspaces.settings.connection")}
        <select
          required
          disabled={locked}
          value={connectionId}
          onChange={(e) => setConnectionId(e.target.value)}
        >
          <option value="">{t("workspaces.settings.noConnection")}</option>
          {connections.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label} — {c.base_url}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        {t("workspaces.settings.repoUrl")}
        <input
          required
          type="url"
          disabled={locked}
          placeholder={connection ? `${connection.base_url}/depot` : undefined}
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
        />
      </label>
      {connection && (
        <p className="help">{t("workspaces.settings.repoHelp", { base: connection.base_url })}</p>
      )}
      {locked ? (
        <p className="muted">{t("workspaces.settings.lockedByWorkBranch")}</p>
      ) : (
        <p className="alert">{t("workspaces.form.writesForReal", { branch: verificationBranch(suffix) })}</p>
      )}
      {testing && (
        <p className="muted" role="status">
          {t("workspaces.form.testing", { branch: verificationBranch(suffix) })}
        </p>
      )}
      {save.isError && <p className="alert" role="alert">{t(errorKey(save.error))}</p>}
      {refused ? <AccessReportView report={refused} /> : report && <AccessReportView report={report} />}
      <div className="actions">
        {!locked && (
          <button type="submit" className="btn btn-primary" disabled={testing || !connectionId}>
            {t("workspaces.settings.saveRepo")}
          </button>
        )}
        {workspace.repo_url && (
          <button
            type="button"
            className="btn btn-secondary"
            disabled={testing}
            onClick={() =>
              recheck.mutate(suffix, { onSettled: () => setSuffix(newVerificationSuffix()) })
            }
          >
            {t("workspaces.card.recheck")}
          </button>
        )}
      </div>
    </form>
  );
}

function SecurityCard({ workspace }: { workspace: Workspace }) {
  const { t } = useTranslation();
  const services = useSecurityServices();
  const save = useSetSecurityService(workspace.id);
  const [serviceId, setServiceId] = useState(workspace.security_service_id ?? "");

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate(serviceId || null);
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("workspaces.settings.securityTitle")}>
      <h2>{t("workspaces.settings.securityTitle")}</h2>
      <label className="field">
        {t("workspaces.fields.securityService")}
        <select value={serviceId} onChange={(e) => setServiceId(e.target.value)}>
          <option value="">{t("workspaces.fields.noSecurityService")}</option>
          {services.data?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.id} — {s.base_url}
            </option>
          ))}
        </select>
      </label>
      {save.isSuccess && <p className="notice" role="status">{t("workspaces.settings.saved")}</p>}
      {save.isError && <p className="alert" role="alert">{t(errorKey(save.error))}</p>}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={save.isPending}>
          {t("workspaces.settings.saveSecurity")}
        </button>
      </div>
    </form>
  );
}

/** Sous-écran « Paramétrage » d'un workspace : tout ce que la création ne demande plus. */
export function WorkspaceSettings({
  workspace,
  onBack,
  onOpenBranch,
}: {
  workspace: Workspace;
  onBack: () => void;
  // Ouvrir la branche qu'on vient de créer. Absent : le paramétrage ne navigue pas.
  onOpenBranch?: (slug: string) => void;
}) {
  const { t } = useTranslation();
  const [branching, setBranching] = useState(false);
  return (
    <section aria-labelledby="workspace-settings-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("workspaces.settings.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="workspace-settings-title">
            {t("workspaces.settings.title", { name: workspace.name })}
          </h1>
          <p className="lead mono">{workspace.id}</p>
        </div>
      </div>
      <RepositoryCard workspace={workspace} />
      <SecurityCard workspace={workspace} />
      <div className="card">
        <h2>{t("workspaces.work.title")}</h2>
        {/* Sans dépôt, la branche de travail n'a nulle part où s'ouvrir. */}
        {workspace.repo_url ? (
          <WorkBranchPanel workspace={workspace} />
        ) : (
          <p className="muted">{t("workspaces.settings.needsRepository")}</p>
        )}
        {/* La prise de main suit la création de branche hors de la liste : elle porte sur
            la branche AFFICHÉE, que le sélecteur de la liste choisit toujours. Sans ce
            toit, le geste n'aurait plus d'écran du tout. */}
        {workspace.work_branch !== null && <HoldControl workspace={workspace} />}
        {/* La création d'une branche a quitté la liste des workspaces (Gael, 24/10/2026) :
            elle vit là où l'on règle le workspace, à côté de la branche de base. */}
        {workspace.work_branch !== null && !branching && (
          <button type="button" className="btn btn-secondary" onClick={() => setBranching(true)}>
            {t("branches.add")}
          </button>
        )}
      </div>
      {branching && (
        <BranchForm
          workspace={workspace}
          onDone={(slug) => {
            setBranching(false);
            if (slug) {
              onOpenBranch?.(slug);
            }
          }}
        />
      )}
    </section>
  );
}
