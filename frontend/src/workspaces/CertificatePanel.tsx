import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, invalidField } from "../api/http";
import {
  type Workspace,
  daysUntil,
  newVerificationSuffix,
  useReplaceCertificate,
} from "../api/workspaces";
import { SecretPicker } from "../secrets/SecretPicker";

// Au-delà, l'échéance s'annonce sans alarme ; en deçà, elle devient une alerte.
const WARNING_DAYS = 30;

export function CertificateFields({
  certPem,
  keySlug,
  onCertPem,
  onKeySlug,
}: {
  certPem: string;
  keySlug: string | null;
  onCertPem: (value: string) => void;
  onKeySlug: (value: string | null) => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      <label className="field">
        {t("workspaces.cert.pem")}
        <textarea rows={4} value={certPem} onChange={(e) => onCertPem(e.target.value)} />
      </label>
      <SecretPicker
        label={t("workspaces.cert.key")}
        secretType="GIT_CLIENT_KEY"
        value={keySlug}
        onChange={onKeySlug}
      />
    </>
  );
}

function errorKey(error: unknown): string {
  const field = invalidField(error);
  if (field !== null) {
    const reason = (error as ApiError).detail as { reason?: string };
    return reason.reason ? `workspaces.cert.errors.${reason.reason}` : `workspaces.errors.invalid.${field}`;
  }
  if (error instanceof ApiError && error.status === 422) {
    return "workspaces.cert.errors.access";
  }
  return "workspaces.errors.unexpected";
}

/** Échéance du certificat client et remplacement sans recréer le workspace. */
export function CertificatePanel({ workspace }: { workspace: Workspace }) {
  const { t } = useTranslation();
  const replace = useReplaceCertificate(workspace.id);
  const [editing, setEditing] = useState(false);
  const [certPem, setCertPem] = useState("");
  const [keySlug, setKeySlug] = useState<string | null>(null);
  const expiry = workspace.client_cert_not_after;
  const days = expiry ? daysUntil(expiry) : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (keySlug === null) {
      return;
    }
    replace.mutate(
      { cert_pem: certPem, key_secret_slug: keySlug, verification_suffix: newVerificationSuffix() },
      { onSuccess: () => setEditing(false) },
    );
  }

  return (
    <div className="panel">
      <h3>{t("workspaces.cert.legend")}</h3>
      {expiry === null || days === null ? (
        <p className="muted">{t("workspaces.cert.none")}</p>
      ) : (
        <p className={days < WARNING_DAYS ? "alert" : "muted"} role={days < WARNING_DAYS ? "alert" : undefined}>
          {t(days < 0 ? "workspaces.cert.expired" : "workspaces.cert.expires", {
            date: new Date(expiry).toLocaleDateString(),
            count: Math.max(days, 0),
          })}
        </p>
      )}
      {editing ? (
        <form onSubmit={submit} aria-label={t("workspaces.cert.replace")}>
          <CertificateFields
            certPem={certPem}
            keySlug={keySlug}
            onCertPem={setCertPem}
            onKeySlug={setKeySlug}
          />
          <p className="help">{t("workspaces.cert.testedFirst")}</p>
          {replace.isError && <p className="alert" role="alert">{t(errorKey(replace.error))}</p>}
          <button type="submit" className="btn btn-primary" disabled={replace.isPending || keySlug === null || certPem === ""}>
            {t("workspaces.cert.save")}
          </button>
        </form>
      ) : (
        <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)}>
          {t(expiry ? "workspaces.cert.replace" : "workspaces.cert.add")}
        </button>
      )}
    </div>
  );
}
