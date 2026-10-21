import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

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
  const [suffix, setSuffix] = useState(newVerificationSuffix);
  const refused = failedReport(create.error);

  function submit(event: FormEvent) {
    event.preventDefault();
    const input = {
      id,
      name,
      repo_url: repoUrl,
      git_secret_slug: secret,
      security_service_id: service || null,
      verification_suffix: suffix,
    };
    // Un essai = un nom de branche : le suivant en tire un autre, pour ne jamais
    // retomber sur une branche résiduelle d'un essai précédent.
    create.mutate(input, { onSuccess: onDone, onSettled: () => setSuffix(newVerificationSuffix()) });
  }

  return (
    <form onSubmit={submit} aria-label={t("workspaces.form.title")}>
      <label>
        {t("workspaces.fields.id")}
        <input required value={id} onChange={(e) => setId(e.target.value)} />
      </label>
      <label>
        {t("workspaces.fields.name")}
        <input required value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        {t("workspaces.fields.repoUrl")}
        <input
          required
          type="url"
          placeholder="https://github.com/organisation/parametrage"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
        />
      </label>
      <SecretPicker
        label={t("workspaces.fields.gitSecret")}
        secretType="GIT_TOKEN"
        value={secret}
        onChange={setSecret}
      />
      <label>
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
      <p>{t("workspaces.form.writesForReal", { branch: verificationBranch(suffix) })}</p>
      {create.isPending && (
        <p role="status">{t("workspaces.form.testing", { branch: verificationBranch(suffix) })}</p>
      )}
      {create.isError && <p role="alert">{t(errorKey(create.error))}</p>}
      {refused && <AccessReportView report={refused} />}
      <button type="submit" disabled={create.isPending || secret === null}>
        {t("workspaces.form.submit")}
      </button>
      <button type="button" onClick={onDone}>
        {t("workspaces.form.cancel")}
      </button>
    </form>
  );
}

function WorkspaceCard({ workspace }: { workspace: Workspace }) {
  const { t } = useTranslation();
  const recheck = useRecheckWorkspace(workspace.id);
  const [suffix, setSuffix] = useState(newVerificationSuffix);
  const report = recheck.data ?? workspace.last_check;

  return (
    <li>
      <strong>{workspace.name}</strong> <code>{workspace.id}</code> — {workspace.repo_url}
      <p>
        {workspace.security_service_id
          ? t("workspaces.card.securityService", { id: workspace.security_service_id })
          : t("workspaces.card.noSecurityService")}
      </p>
      <button
        type="button"
        disabled={recheck.isPending}
        onClick={() => recheck.mutate(suffix, { onSettled: () => setSuffix(newVerificationSuffix()) })}
      >
        {t("workspaces.card.recheck")}
      </button>
      {recheck.isPending && (
        <p role="status">{t("workspaces.form.testing", { branch: verificationBranch(suffix) })}</p>
      )}
      {report && <AccessReportView report={report} />}
      <WorkBranchPanel workspace={workspace} />
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
      <h2 id="workspaces-title">{t("workspaces.title")}</h2>
      <p>{t("workspaces.intro")}</p>
      {creating ? (
        <CreateForm onDone={() => setCreating(false)} />
      ) : (
        <button type="button" onClick={() => setCreating(true)}>
          {t("workspaces.add")}
        </button>
      )}
      {workspaces.isError && <p role="alert">{t("workspaces.errors.unreachable")}</p>}
      {workspaces.isSuccess && workspaces.data.length === 0 && <p>{t("workspaces.empty")}</p>}
      <ul>
        {workspaces.data?.map((w) => <WorkspaceCard key={w.id} workspace={w} />)}
      </ul>
    </section>
  );
}
