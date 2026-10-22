import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type ApiKey,
  type Grant,
  type IssuedKey,
  useApiKeys,
  useIssueApiKey,
  useMcpEndpoint,
  useRevokeApiKey,
  useSetApiKeyGrants,
} from "../api/apiKeys";
import { invalidField } from "../api/http";
import { ConfirmDialog } from "../layout/ConfirmDialog";
import { CopyButton } from "../layout/CopyButton";
import { PageHead } from "../layout/PageHead";
import { GrantsEditor } from "./GrantsEditor";

function errorKey(error: unknown): string {
  const field = invalidField(error);
  return field === null ? "apiKeys.errors.unexpected" : `apiKeys.errors.invalid.${field}`;
}

/** L'adresse à déclarer dans la gateway du portail, avec la façon d'y présenter la clé. */
function EndpointCard() {
  const { t } = useTranslation();
  const endpoint = useMcpEndpoint();
  if (!endpoint.data) {
    return null;
  }
  const { url, path } = endpoint.data;
  return (
    <section className="card" aria-labelledby="mcp-endpoint-title">
      <h2 id="mcp-endpoint-title">{t("apiKeys.endpoint.title")}</h2>
      {url !== null ? (
        <div className="actions">
          <code className="mono" aria-label={t("apiKeys.endpoint.url")}>{url}</code>
          <CopyButton text={url} label={t("apiKeys.endpoint.copy")} />
        </div>
      ) : (
        <p className="alert" role="alert">{t("apiKeys.endpoint.unset", { path })}</p>
      )}
      <p className="help">{t("apiKeys.endpoint.help")}</p>
    </section>
  );
}

/** La clé en clair, cette seule fois : on la copie maintenant ou on en émet une autre. */
function IssuedNotice({ issued, onDone }: { issued: IssuedKey; onDone: () => void }) {
  const { t } = useTranslation();
  return (
    <section className="card notice" aria-labelledby="issued-title" role="status">
      <h2 id="issued-title">{t("apiKeys.issued.title", { label: issued.key.label })}</h2>
      <p>{t("apiKeys.issued.once")}</p>
      <pre className="mono code-block" aria-label={t("apiKeys.issued.secret")}>{issued.secret}</pre>
      <div className="actions">
        <CopyButton text={issued.secret} label={t("apiKeys.issued.copy")} />
        <button type="button" className="btn btn-primary" onClick={onDone}>
          {t("apiKeys.issued.done")}
        </button>
      </div>
    </section>
  );
}

function IssueForm({ onIssued, onCancel }: { onIssued: (issued: IssuedKey) => void; onCancel: () => void }) {
  const { t } = useTranslation();
  const issue = useIssueApiKey();
  const [label, setLabel] = useState("");
  const [grants, setGrants] = useState<Grant[]>([]);

  function submit(event: FormEvent) {
    event.preventDefault();
    issue.mutate({ label, grants }, { onSuccess: onIssued });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("apiKeys.form.title")}>
      <h2>{t("apiKeys.form.title")}</h2>
      <label className="field">
        {t("apiKeys.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <GrantsEditor grants={grants} onChange={setGrants} />
      {issue.isError && <p className="alert" role="alert">{t(errorKey(issue.error))}</p>}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={issue.isPending}>
          {t("apiKeys.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function KeyRow({ apiKey }: { apiKey: ApiKey }) {
  const { t, i18n } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [grants, setGrants] = useState<Grant[]>(apiKey.grants);
  const [confirming, setConfirming] = useState(false);
  const save = useSetApiKeyGrants(apiKey.id);
  const revoke = useRevokeApiKey(apiKey.id);
  const date = (value: string | null) => (value ? new Date(value).toLocaleString(i18n.language) : t("apiKeys.list.never"));
  const revoked = apiKey.revoked_at !== null;

  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">
          {apiKey.label} {revoked && <span className="badge">{t("apiKeys.list.revoked")}</span>}
        </div>
        <div className="row-sub">
          <span className="mono">{apiKey.prefix}…</span> · {t("apiKeys.list.issued", { date: date(apiKey.created_at), by: apiKey.created_by })}
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("apiKeys.fields.grants")}</div>
        <div className="value">
          {apiKey.grants.length === 0
            ? t("apiKeys.list.noGrant")
            : apiKey.grants.map((g) => `${g.workspace_id} (${t(`apiKeys.access.${g.access}`)})`).join(", ")}
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("apiKeys.list.lastUsed")}</div>
        <div className="value">{date(apiKey.last_used_at)}</div>
      </div>
      {!revoked && (
        <div className="actions row-actions">
          <button type="button" className="btn btn-secondary" onClick={() => { setGrants(apiKey.grants); setEditing(!editing); }}>
            {t("apiKeys.list.editGrants")}
          </button>
          <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
            {t("apiKeys.list.revoke")}
          </button>
        </div>
      )}
      {editing && (
        <div className="row-detail">
          <GrantsEditor grants={grants} onChange={setGrants} />
          {save.isError && <p className="alert" role="alert">{t(errorKey(save.error))}</p>}
          <button type="button" className="btn btn-primary" disabled={save.isPending} onClick={() => save.mutate(grants, { onSuccess: () => setEditing(false) })}>
            {t("apiKeys.list.saveGrants")}
          </button>
        </div>
      )}
      {revoke.isError && <p className="alert row-detail" role="alert">{t("apiKeys.errors.unexpected")}</p>}
      {confirming && (
        <ConfirmDialog
          title={t("apiKeys.revokeConfirm.title", { label: apiKey.label })}
          confirmLabel={t("apiKeys.list.revoke")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            revoke.mutate();
          }}
        >
          {t("apiKeys.revokeConfirm.body")}
        </ConfirmDialog>
      )}
    </li>
  );
}

/** Clés d'API de service (story 0d4e4f75) : ce que la gateway du portail présente à /mcp/. */
export function ApiKeysScreen() {
  const { t } = useTranslation();
  const keys = useApiKeys();
  const [issuing, setIssuing] = useState(false);
  const [issued, setIssued] = useState<IssuedKey | null>(null);

  return (
    <section aria-labelledby="api-keys-title">
      <PageHead
        id="api-keys-title"
        title={t("apiKeys.title")}
        lead={t("apiKeys.intro")}
        action={
          !issuing && issued === null ? (
            <button type="button" className="btn btn-primary" onClick={() => setIssuing(true)}>
              {t("apiKeys.add")}
            </button>
          ) : undefined
        }
      />
      <EndpointCard />
      {issued !== null && <IssuedNotice issued={issued} onDone={() => setIssued(null)} />}
      {issuing && (
        <IssueForm
          onIssued={(next) => {
            setIssuing(false);
            setIssued(next);
          }}
          onCancel={() => setIssuing(false)}
        />
      )}
      {keys.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {keys.isError && <p className="alert" role="alert">{t("apiKeys.errors.unexpected")}</p>}
      {keys.isSuccess && keys.data.length === 0 && <p className="muted">{t("apiKeys.empty")}</p>}
      {keys.isSuccess && keys.data.length > 0 && (
        <ul className="card-list plain-list">
          {keys.data.map((k) => (
            <KeyRow key={k.id} apiKey={k} />
          ))}
        </ul>
      )}
    </section>
  );
}
