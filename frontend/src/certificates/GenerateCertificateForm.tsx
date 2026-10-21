import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { type ClientCertificate, useGenerateCertificate } from "../api/gitAccess";
import { errorMessage } from "../api/gitAccessErrors";
import { slugFromLabel } from "../api/secrets";
import { PublicParts } from "./CopyField";

// Arbitrage du 21/10/2026 : la durée se saisit, un an par défaut.
const DEFAULT_DAYS = 365;
const MAX_DAYS = 3650;

/**
 * Génération d'un certificat auto-signé (story 9265f111). Une fois généré, le formulaire
 * laisse place à ses parties publiques à copier : c'est à ce moment qu'on les déclare
 * côté forge. `onDone` rend le certificat généré, ou rien sur une annulation.
 */
export function GenerateCertificateForm({
  onDone,
}: {
  onDone: (generated?: ClientCertificate) => void;
}) {
  const { t } = useTranslation();
  const generate = useGenerateCertificate();
  const [label, setLabel] = useState("");
  const [id, setId] = useState("");
  const [idTouched, setIdTouched] = useState(false);
  const [days, setDays] = useState(String(DEFAULT_DAYS));
  // L'identifiant suit le libellé tant qu'on ne l'a pas saisi soi-même.
  const shownId = idTouched ? id : slugFromLabel(label);
  const generated = generate.data;

  function submit(event: FormEvent) {
    event.preventDefault();
    // Ouvert depuis le formulaire d'une connexion, par un portail : sans cet arrêt, la
    // validation remonterait l'arbre React et soumettrait aussi la connexion.
    event.stopPropagation();
    generate.mutate({ id: shownId, label, validity_days: Number(days) });
  }

  if (generated) {
    return (
      <section className="card" aria-label={t("certificates.generateForm.title")}>
        <h2>{t("certificates.generateForm.resultTitle", { label: generated.label })}</h2>
        <p className="help">{t("certificates.generateForm.resultHelp")}</p>
        <PublicParts publicKey={generated.public_key_pem} certificate={generated.cert_pem} />
        <div className="actions">
          <button type="button" className="btn btn-primary" onClick={() => onDone(generated)}>
            {t("certificates.generateForm.done")}
          </button>
        </div>
      </section>
    );
  }
  return (
    <form className="card" onSubmit={submit} aria-label={t("certificates.generateForm.title")}>
      <h2>{t("certificates.generateForm.title")}</h2>
      <p className="help">{t("certificates.generateForm.help")}</p>
      <label className="field">
        {t("certificates.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
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
      <label className="field">
        {t("certificates.fields.days")}
        <input
          required
          type="number"
          min={1}
          max={MAX_DAYS}
          value={days}
          onChange={(e) => setDays(e.target.value)}
        />
      </label>
      {generate.isError && (
        <p className="alert" role="alert">{errorMessage(t, "certificates", generate.error)}</p>
      )}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={generate.isPending}>
          {t("certificates.generateForm.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => onDone()}>
          {t("certificates.form.cancel")}
        </button>
      </div>
    </form>
  );
}
