import { type FormEvent, useId, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import {
  type GitConnection,
  useCertificates,
  useConnections,
  useCreateConnection,
  useDeleteConnection,
  useUpdateConnection,
} from "../api/gitAccess";
import { dependentFailure, errorMessage, usedBy } from "../api/gitAccessErrors";
import { slugFromLabel } from "../api/secrets";
import { newVerificationSuffix } from "../api/workspaces";
import { CertificateForm } from "../certificates/CertificatesScreen";
import { ConfirmDialog } from "../layout/ConfirmDialog";
import { PageHead } from "../layout/PageHead";
import { SecretPicker } from "../secrets/SecretPicker";
import { AccessReportView } from "../workspaces/AccessReportView";

/** Déclaration (sans `connection`) ou modification (avec), remontée par `key` à chaque ouverture. */
function ConnectionForm({ connection, onDone }: { connection?: GitConnection; onDone: () => void }) {
  const { t } = useTranslation();
  const certificates = useCertificates();
  const create = useCreateConnection();
  const update = useUpdateConnection(connection?.id ?? "");
  const save = connection ? update : create;
  const [label, setLabel] = useState(connection?.label ?? "");
  const [id, setId] = useState("");
  const [idTouched, setIdTouched] = useState(false);
  const [baseUrl, setBaseUrl] = useState(connection?.base_url ?? "");
  const [token, setToken] = useState<string | null>(connection?.token_secret_slug ?? null);
  const [certificate, setCertificate] = useState(connection?.certificate_id ?? "");
  const [creatingCertificate, setCreatingCertificate] = useState(false);
  const failure = dependentFailure(save.error);
  const certificateFieldId = useId();
  // L'identifiant suit le libellé tant qu'on ne l'a pas saisi soi-même.
  const shownId = idTouched ? id : slugFromLabel(label);
  // PAT, certificat ou les deux (21/10/2026) : jamais aucun.
  const noAccess = token === null && certificate === "";

  function submit(event: FormEvent) {
    event.preventDefault();
    const input = {
      label,
      base_url: baseUrl,
      token_secret_slug: token,
      certificate_id: certificate || null,
    };
    if (connection) {
      update.mutate({ ...input, verification_suffix: newVerificationSuffix() }, { onSuccess: onDone });
    } else {
      create.mutate({ ...input, id: shownId }, { onSuccess: onDone });
    }
  }

  const title = connection
    ? t("gitConnections.form.editTitle", { label: connection.label })
    : t("gitConnections.form.newTitle");
  return (
    <form className="card" onSubmit={submit} aria-label={title}>
      <h2>{title}</h2>
      <label className="field">
        {t("gitConnections.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      {!connection && (
        <label className="field">
          {t("gitConnections.fields.id")}
          <input
            required
            value={shownId}
            onChange={(e) => {
              setIdTouched(true);
              setId(e.target.value);
            }}
          />
        </label>
      )}
      <label className="field">
        {t("gitConnections.fields.baseUrl")}
        <input
          required
          type="url"
          placeholder="https://github.com/mon-organisation"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
        />
      </label>
      <p className="help">{t("gitConnections.form.baseUrlHelp")}</p>
      <fieldset>
        <legend>{t("gitConnections.form.access")}</legend>
        <SecretPicker
          label={t("gitConnections.fields.token")}
          secretType="GIT_TOKEN"
          value={token}
          onChange={setToken}
        />
        <div className="field">
          <label htmlFor={certificateFieldId}>{t("gitConnections.fields.certificate")}</label>
          <div className="field-row">
            <select
              id={certificateFieldId}
              value={certificate}
              onChange={(e) => setCertificate(e.target.value)}
            >
              <option value="">{t("gitConnections.fields.noCertificate")}</option>
              {certificates.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setCreatingCertificate(true)}
            >
              {t("gitConnections.fields.createCertificate")}
            </button>
          </div>
        </div>
        {/* Hors du formulaire dans le DOM (un formulaire ne s'imbrique pas), au-dessus
            de l'écran : la saisie de la connexion en cours n'est pas perdue. */}
        {creatingCertificate &&
          createPortal(
            <div className="overlay">
              <div
                className="dialog dialog-wide"
                role="dialog"
                aria-modal="true"
                aria-label={t("certificates.form.newTitle")}
              >
                <CertificateForm
                  onDone={(saved) => {
                    setCreatingCertificate(false);
                    if (saved) {
                      setCertificate(saved.id);
                    }
                  }}
                />
              </div>
            </div>,
            document.body,
          )}
        <p className="help">{t("gitConnections.form.atLeastOne")}</p>
      </fieldset>
      {connection && connection.workspaces.length > 0 && (
        <p className="alert">
          {t("gitConnections.form.testedFirst", { count: connection.workspaces.length })}
        </p>
      )}
      {save.isError && (
        <p className="alert" role="alert">{errorMessage(t, "gitConnections", save.error)}</p>
      )}
      {failure?.report && <AccessReportView report={failure.report} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={save.isPending || noAccess}>
          {t(connection ? "gitConnections.form.saveEdit" : "gitConnections.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDone}>
          {t("gitConnections.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function ConnectionRow({ connection }: { connection: GitConnection }) {
  const { t } = useTranslation();
  const remove = useDeleteConnection();
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const blockers = usedBy(remove.error);

  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{connection.label}</div>
        <div className="row-sub">{connection.base_url}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("gitConnections.list.captionAccess")}</div>
        <div className="value">
          {connection.token_secret_slug && (
            <span className="badge badge-accent">{t("gitConnections.list.pat")}</span>
          )}{" "}
          {connection.certificate_id && (
            <span className="badge badge-accent">{t("gitConnections.list.certificate")}</span>
          )}
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("gitConnections.list.captionUsage")}</div>
        <div className="value">
          {t("gitConnections.list.usedBy", { count: connection.workspaces.length })}
        </div>
      </div>
      <div className="actions row-actions">
        <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)}>
          {t("gitConnections.list.edit")}
        </button>
        <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
          {t("gitConnections.list.delete")}
        </button>
      </div>
      {editing && (
        <div className="row-detail">
          <ConnectionForm connection={connection} onDone={() => setEditing(false)} />
        </div>
      )}
      {blockers !== null && (
        <p className="alert row-detail" role="alert">
          {t("gitConnections.errors.inUse", { list: blockers.join(", ") })}
        </p>
      )}
      {remove.isError && blockers === null && (
        <p className="alert row-detail" role="alert">{t("gitConnections.errors.unexpected")}</p>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("gitConnections.deleteConfirm.title")}
          confirmLabel={t("gitConnections.deleteConfirm.confirm")}
          cancelLabel={t("gitConnections.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate(connection.id);
          }}
        >
          <p>{t("gitConnections.deleteConfirm.body", { label: connection.label })}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

/** Connexions aux forges git : l'adresse et l'accès, choisis ensuite par les workspaces. */
export function GitConnectionsScreen() {
  const { t } = useTranslation();
  const connections = useConnections();
  const [creating, setCreating] = useState(false);

  return (
    <section aria-labelledby="git-connections-title">
      <PageHead
        id="git-connections-title"
        title={t("gitConnections.title")}
        lead={t("gitConnections.intro")}
        action={
          !creating && (
            <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
              {t("gitConnections.add")}
            </button>
          )
        }
      />
      {creating && <ConnectionForm onDone={() => setCreating(false)} />}
      {connections.isPending && (
        <p className="muted" role="status">{t("gitConnections.loading")}</p>
      )}
      {connections.isError && (
        <p className="alert" role="alert">{t("gitConnections.errors.unreachable")}</p>
      )}
      {connections.isSuccess && connections.data.length === 0 && (
        <p className="muted">{t("gitConnections.empty")}</p>
      )}
      {connections.isSuccess && connections.data.length > 0 && (
        <ul className="card-list plain-list">
          {connections.data.map((c) => (
            <ConnectionRow key={c.id} connection={c} />
          ))}
        </ul>
      )}
    </section>
  );
}
