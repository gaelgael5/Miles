import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { invalidField } from "../api/http";
import { type OAuthClient, useDeclareOAuthClient, useDeleteOAuthClient, useOAuthClients, useOAuthEndpoints } from "../api/oauth";
import { ConfirmDialog } from "../layout/ConfirmDialog";
import { CopyButton } from "../layout/CopyButton";
import { PageHead } from "../layout/PageHead";

function errorKey(error: unknown): string {
  const field = invalidField(error);
  return field === null ? "oauth.errors.unexpected" : `oauth.errors.invalid.${field}`;
}

/** Ce qu'il faut saisir dans claude.ai : l'adresse MCP, puis le client_id d'un client ci-dessous. */
function Endpoints() {
  const { t } = useTranslation();
  const endpoints = useOAuthEndpoints();
  const url = endpoints.data?.mcp_url;
  if (!endpoints.data) {
    return null;
  }
  return (
    <section className="card" aria-labelledby="oauth-endpoints-title">
      <h2 id="oauth-endpoints-title">{t("oauth.endpoints.title")}</h2>
      {url ? (
        <>
          <label className="field">
            {t("oauth.endpoints.mcpUrl")}
            <input readOnly className="mono" value={url} onFocus={(e) => e.target.select()} />
          </label>
          <p className="help">{t("oauth.endpoints.help")}</p>
          <div className="actions">
            <CopyButton text={url} label={t("apiKeys.endpoint.copy")} />
          </div>
        </>
      ) : (
        <p className="alert" role="alert">{t("oauth.endpoints.unset")}</p>
      )}
    </section>
  );
}

function DeclareForm({ suggested, onDone }: { suggested: string[]; onDone: () => void }) {
  const { t } = useTranslation();
  const declare = useDeclareOAuthClient();
  const [label, setLabel] = useState("claude.ai");
  const [uris, setUris] = useState(suggested.join("\n"));

  function submit(event: FormEvent) {
    event.preventDefault();
    const redirect_uris = uris.split("\n").map((u) => u.trim()).filter((u) => u !== "");
    declare.mutate({ label, redirect_uris }, { onSuccess: onDone });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("oauth.form.title")}>
      <h2>{t("oauth.form.title")}</h2>
      <label className="field">
        {t("oauth.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label className="field">
        {t("oauth.fields.redirectUris")}
        <textarea required rows={3} className="mono" spellCheck={false} value={uris} onChange={(e) => setUris(e.target.value)} />
      </label>
      <p className="help">{t("oauth.form.redirectHelp")}</p>
      {declare.isError && <p className="alert" role="alert">{t(errorKey(declare.error))}</p>}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={declare.isPending}>
          {t("oauth.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDone}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function ClientRow({ client }: { client: OAuthClient }) {
  const { t } = useTranslation();
  const remove = useDeleteOAuthClient(client.id);
  const [confirming, setConfirming] = useState(false);
  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{client.label}</div>
        <div className="row-sub mono">{client.id}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("oauth.fields.redirectUris")}</div>
        <div className="value mono">{client.redirect_uris.join(", ")}</div>
      </div>
      <div className="actions row-actions">
        <CopyButton text={client.id} label={t("oauth.list.copyId")} />
        <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
          {t("oauth.list.delete")}
        </button>
      </div>
      {remove.isError && <p className="alert row-detail" role="alert">{t("oauth.errors.unexpected")}</p>}
      {confirming && (
        <ConfirmDialog
          title={t("oauth.deleteConfirm.title", { label: client.label })}
          confirmLabel={t("oauth.list.delete")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate();
          }}
        >
          {t("oauth.deleteConfirm.body")}
        </ConfirmDialog>
      )}
    </li>
  );
}

/** Clients OAuth pré-enregistrés (story 9f09cd8b) : claude web s'y connecte à Miles. */
export function OAuthClientsScreen() {
  const { t } = useTranslation();
  const clients = useOAuthClients();
  const endpoints = useOAuthEndpoints();
  const [declaring, setDeclaring] = useState(false);
  const action = !declaring ? (
    <button type="button" className="btn btn-primary" onClick={() => setDeclaring(true)}>
      {t("oauth.add")}
    </button>
  ) : undefined;

  return (
    <section aria-labelledby="oauth-title">
      <PageHead id="oauth-title" title={t("oauth.title")} lead={t("oauth.intro")} action={action} />
      <Endpoints />
      {declaring && endpoints.data && (
        <DeclareForm suggested={endpoints.data.suggested_redirect_uris} onDone={() => setDeclaring(false)} />
      )}
      {clients.isError && <p className="alert" role="alert">{t("oauth.errors.unexpected")}</p>}
      {clients.isSuccess && clients.data.length === 0 && <p className="muted">{t("oauth.empty")}</p>}
      {clients.isSuccess && clients.data.length > 0 && (
        <ul className="card-list plain-list">
          {clients.data.map((c) => (
            <ClientRow key={c.id} client={c} />
          ))}
        </ul>
      )}
    </section>
  );
}
