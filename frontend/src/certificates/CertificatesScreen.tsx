import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type ClientCertificate,
  useCertificates,
  useCreateCertificate,
  useDeleteCertificate,
  useReplaceCertificate,
} from "../api/gitAccess";
import { dependentFailure, errorMessage, usedBy } from "../api/gitAccessErrors";
import { slugFromLabel } from "../api/secrets";
import { daysUntil, newVerificationSuffix } from "../api/workspaces";
import { ConfirmDialog } from "../layout/ConfirmDialog";
import { PageHead } from "../layout/PageHead";
import { SecretPicker } from "../secrets/SecretPicker";
import { AccessReportView } from "../workspaces/AccessReportView";

// Au-delà, l'échéance s'annonce sans alarme ; en deçà, elle devient une alerte.
const WARNING_DAYS = 30;

function Expiry({ notAfter }: { notAfter: string }) {
  const { t } = useTranslation();
  const days = daysUntil(notAfter);
  const date = new Date(notAfter).toLocaleDateString();
  if (days < 0) {
    return <span className="badge badge-warning">{t("certificates.list.expired", { date })}</span>;
  }
  return (
    <span className={days < WARNING_DAYS ? "badge badge-warning" : "badge"}>
      {t("certificates.list.expires", { date, count: days })}
    </span>
  );
}

/** Déclaration (sans `certificate`) ou remplacement éprouvé (avec). */
export function CertificateForm({
  certificate,
  onDone,
}: {
  certificate?: ClientCertificate;
  /** Rend le certificat déclaré ou remplacé ; rien sur une annulation. */
  onDone: (saved?: ClientCertificate) => void;
}) {
  const { t } = useTranslation();
  const create = useCreateCertificate();
  const replace = useReplaceCertificate(certificate?.id ?? "");
  const save = certificate ? replace : create;
  const [label, setLabel] = useState(certificate?.label ?? "");
  const [id, setId] = useState("");
  const [idTouched, setIdTouched] = useState(false);
  const [certPem, setCertPem] = useState("");
  const [keySlug, setKeySlug] = useState<string | null>(null);
  const failure = dependentFailure(save.error);
  // L'identifiant suit le libellé tant qu'on ne l'a pas saisi soi-même.
  const shownId = idTouched ? id : slugFromLabel(label);

  function submit(event: FormEvent) {
    event.preventDefault();
    // Ouvert depuis le formulaire d'une connexion, par un portail : sans cet arrêt, la
    // validation remonterait l'arbre React et soumettrait aussi la connexion.
    event.stopPropagation();
    if (keySlug === null) {
      return;
    }
    const input = { label, cert_pem: certPem, key_secret_slug: keySlug };
    if (certificate) {
      replace.mutate(
        { ...input, verification_suffix: newVerificationSuffix() },
        { onSuccess: (saved) => onDone(saved) },
      );
    } else {
      create.mutate({ ...input, id: shownId }, { onSuccess: (saved) => onDone(saved) });
    }
  }

  const title = certificate
    ? t("certificates.form.replaceTitle", { label: certificate.label })
    : t("certificates.form.newTitle");
  return (
    <form className="card" onSubmit={submit} aria-label={title}>
      <h2>{title}</h2>
      <label className="field">
        {t("certificates.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      {!certificate && (
        <label className="field">
          {t("certificates.fields.id")}
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
        {t("certificates.fields.pem")}
        <textarea required rows={6} value={certPem} onChange={(e) => setCertPem(e.target.value)} />
      </label>
      <SecretPicker
        label={t("certificates.fields.key")}
        secretType="GIT_CLIENT_KEY"
        value={keySlug}
        onChange={setKeySlug}
      />
      {certificate && <p className="help">{t("certificates.form.testedFirst")}</p>}
      {save.isError && (
        <p className="alert" role="alert">{errorMessage(t, "certificates", save.error)}</p>
      )}
      {failure?.report && <AccessReportView report={failure.report} />}
      <div className="actions">
        <button
          type="submit"
          className="btn btn-primary"
          disabled={save.isPending || keySlug === null || certPem.trim() === ""}
        >
          {t(certificate ? "certificates.form.replaceSubmit" : "certificates.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => onDone()}>
          {t("certificates.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function CertificateRow({ certificate }: { certificate: ClientCertificate }) {
  const { t } = useTranslation();
  const remove = useDeleteCertificate();
  const [replacing, setReplacing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const blockers = usedBy(remove.error);

  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{certificate.label}</div>
        <div className="row-sub">{certificate.id}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("certificates.list.captionExpiry")}</div>
        <div className="value">
          <Expiry notAfter={certificate.not_after} />
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("certificates.list.captionUsage")}</div>
        <div className="value">
          {t("certificates.list.usedBy", { count: certificate.connections.length })}
        </div>
      </div>
      <div className="actions row-actions">
        <button type="button" className="btn btn-secondary" onClick={() => setReplacing(true)}>
          {t("certificates.list.replace")}
        </button>
        <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
          {t("certificates.list.delete")}
        </button>
      </div>
      {replacing && (
        <div className="row-detail">
          <CertificateForm certificate={certificate} onDone={() => setReplacing(false)} />
        </div>
      )}
      {blockers !== null && (
        <p className="alert row-detail" role="alert">
          {t("certificates.errors.inUse", { list: blockers.join(", ") })}
        </p>
      )}
      {remove.isError && blockers === null && (
        <p className="alert row-detail" role="alert">{t("certificates.errors.unexpected")}</p>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("certificates.deleteConfirm.title")}
          confirmLabel={t("certificates.deleteConfirm.confirm")}
          cancelLabel={t("certificates.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate(certificate.id);
          }}
        >
          <p>{t("certificates.deleteConfirm.body", { label: certificate.label })}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

/** Certificats clients de la racine : les connexions git les choisissent ensuite. */
export function CertificatesScreen() {
  const { t } = useTranslation();
  const certificates = useCertificates();
  const [creating, setCreating] = useState(false);

  return (
    <section aria-labelledby="certificates-title">
      <PageHead
        id="certificates-title"
        title={t("certificates.title")}
        lead={t("certificates.intro")}
        action={
          !creating && (
            <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
              {t("certificates.add")}
            </button>
          )
        }
      />
      {creating && <CertificateForm onDone={() => setCreating(false)} />}
      {certificates.isPending && <p className="muted" role="status">{t("certificates.loading")}</p>}
      {certificates.isError && (
        <p className="alert" role="alert">{t("certificates.errors.unreachable")}</p>
      )}
      {certificates.isSuccess && certificates.data.length === 0 && (
        <p className="muted">{t("certificates.empty")}</p>
      )}
      {certificates.isSuccess && certificates.data.length > 0 && (
        <ul className="card-list plain-list">
          {certificates.data.map((c) => (
            <CertificateRow key={c.id} certificate={c} />
          ))}
        </ul>
      )}
    </section>
  );
}
