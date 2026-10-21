import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { PageHead } from "../layout/PageHead";
import { ApiError, invalidField } from "../api/http";
import { useSecurityServices } from "../api/security";
import {
  type AccessReport,
  type Workspace,
  newVerificationSuffix,
  useCreateWorkspace,
  useRecheckWorkspace,
  useWorkspaces,
  verificationBranch,
} from "../api/workspaces";
import { SecretPicker } from "../secrets/SecretPicker";
import { AccessReportView } from "./AccessReportView";
import { CertificateFields, CertificatePanel } from "./CertificatePanel";
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
    return `workspaces.errors.invalid.${field}`;
  }
  if (error instanceof ApiError && error.status === 409) {
    return `workspaces.errors.conflict.${String(error.detail)}`;
  }
  if (failedReport(error) !== null) {
    return "workspaces.errors.accessRefused";
  }
  return "workspaces.errors.unexpected";
}

function CreateForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const create = useCreateWorkspace();
  const services = useSecurityServices();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [secret, setSecret] = useState<string | null>(null);
  const [service, setService] = useState<string>("");
  const [certPem, setCertPem] = useState("");
  const [keySlug, setKeySlug] = useState<string | null>(null);
  // Jeton, certificat, ou les deux : au moins l'un des deux (décision du 16/10/2026).
  const withCertificate = certPem.trim() !== "" && keySlug !== null;
  const [suffix, setSuffix] = useState(newVerificationSuffix);
  const refused = failedReport(create.error);

  function submit(event: FormEvent) {
    event.preventDefault();
    const input = {
      id,
      name,
      repo_url: repoUrl,
      git_secret_slug: secret,
      client_certificate: withCertificate ? { cert_pem: certPem, key_secret_slug: keySlug } : null,
      security_service_id: service || null,
      verification_suffix: suffix,
    };
    // Un essai = un nom de branche : le suivant en tire un autre, pour ne jamais
    // retomber sur une branche résiduelle d'un essai précédent.
    create.mutate(input, { onSuccess: onDone, onSettled: () => setSuffix(newVerificationSuffix()) });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("workspaces.form.title")}>
      <div className="step">
        <span className="step-number">1</span>
        <h2>{t("workspaces.form.stepIdentity")}</h2>
      </div>
      <label className="field">
        {t("workspaces.fields.id")}
        <input required value={id} onChange={(e) => setId(e.target.value)} />
      </label>
      <label className="field">
        {t("workspaces.fields.name")}
        <input required value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field">
        {t("workspaces.fields.repoUrl")}
        <input
          required
          type="url"
          placeholder="https://github.com/organisation/parametrage"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
        />
      </label>
      <div className="step">
        <span className="step-number">2</span>
        <h2>{t("workspaces.form.stepAccess")}</h2>
      </div>
      <SecretPicker
        label={t("workspaces.fields.gitSecret")}
        secretType="GIT_TOKEN"
        value={secret}
        onChange={setSecret}
      />
      <fieldset>
        <legend>{t("workspaces.cert.legend")}</legend>
        <CertificateFields
          certPem={certPem}
          keySlug={keySlug}
          onCertPem={setCertPem}
          onKeySlug={setKeySlug}
        />
      </fieldset>
      <div className="step">
        <span className="step-number">3</span>
        <h2>{t("workspaces.form.stepSecurity")}</h2>
      </div>
      <label className="field">
        {t("workspaces.fields.securityService")}
        <select value={service} onChange={(e) => setService(e.target.value)}>
          <option value="">{t("workspaces.fields.noSecurityService")}</option>
          {services.data?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.id} — {s.base_url}
            </option>
          ))}
        </select>
      </label>
      <p className="alert">{t("workspaces.form.writesForReal", { branch: verificationBranch(suffix) })}</p>
      {create.isPending && (
        <p className="muted" role="status">{t("workspaces.form.testing", { branch: verificationBranch(suffix) })}</p>
      )}
      {create.isError && <p className="alert" role="alert">{t(errorKey(create.error))}</p>}
      {refused && <AccessReportView report={refused} />}
      <div className="actions">
      <button type="submit" className="btn btn-primary" disabled={create.isPending || (secret === null && !withCertificate)}>
        {t("workspaces.form.submit")}
      </button>
      <button type="button" className="btn btn-secondary" onClick={onDone}>
        {t("workspaces.form.cancel")}
      </button>
      </div>
    </form>
  );
}

function WorkspaceCard({ workspace }: { workspace: Workspace }) {
  const { t } = useTranslation();
  const recheck = useRecheckWorkspace(workspace.id);
  const [suffix, setSuffix] = useState(newVerificationSuffix);
  const report = recheck.data ?? workspace.last_check;

  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{workspace.name}</div>
        <div className="row-sub">
          {workspace.id} · {workspace.repo_url}
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("workspaces.card.captionSecurity")}</div>
        <div className="value">
          {workspace.security_service_id
            ? t("workspaces.card.securityService", { id: workspace.security_service_id })
            : t("workspaces.card.noSecurityService")}
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("workspaces.card.captionWorkBranch")}</div>
        <div className="value mono">{workspace.work_branch ?? "—"}</div>
      </div>
      <div className="actions row-actions">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={recheck.isPending}
          onClick={() => recheck.mutate(suffix, { onSettled: () => setSuffix(newVerificationSuffix()) })}
        >
          {t("workspaces.card.recheck")}
        </button>
      </div>
      <div className="row-detail">
        {recheck.isPending && (
          <p className="muted" role="status">{t("workspaces.form.testing", { branch: verificationBranch(suffix) })}</p>
        )}
        {report && <AccessReportView report={report} />}
        <CertificatePanel workspace={workspace} />
        <WorkBranchPanel workspace={workspace} />
      </div>
    </li>
  );
}

/** Workspaces : une application métier chacun, avec son dépôt et ses cinq droits éprouvés. */
export function WorkspacesScreen() {
  const { t } = useTranslation();
  const workspaces = useWorkspaces();
  const [creating, setCreating] = useState(false);

  return (
    <section aria-labelledby="workspaces-title">
      <PageHead
        id="workspaces-title"
        title={t("workspaces.title")}
        lead={t("workspaces.intro")}
        action={
          !creating && (
            <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
              {t("workspaces.add")}
            </button>
          )
        }
      />
      {creating && <CreateForm onDone={() => setCreating(false)} />}
      {workspaces.isError && <p className="alert" role="alert">{t("workspaces.errors.unreachable")}</p>}
      {workspaces.isSuccess && workspaces.data.length === 0 && <p>{t("workspaces.empty")}</p>}
      {(workspaces.data?.length ?? 0) > 0 && (
        <ul className="card-list plain-list">
          {workspaces.data?.map((w) => <WorkspaceCard key={w.id} workspace={w} />)}
        </ul>
      )}
    </section>
  );
}
