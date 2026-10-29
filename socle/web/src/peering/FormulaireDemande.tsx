import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "../layout/ConfirmDialog";

import { useRequestPairing } from "../api/peering";
import { Refus } from "./Refus";

export function FormulaireDemande({ reappariement }: { reappariement: boolean }) {
  const { t } = useTranslation();
  const [baseUrl, setBaseUrl] = useState("");
  const [nom, setNom] = useState("");
  const [confirme, setConfirme] = useState(false);
  const demande = useRequestPairing();

  function envoyer() {
    demande.mutate({ base_url: baseUrl, name: nom });
  }

  function soumettre(event: FormEvent) {
    event.preventDefault();
    // Un ré-appariement remplace l'appariement courant et prive l'environnement des
    // devices que le module précédent lui avait affectés : jamais sans avertissement.
    if (reappariement) {
      setConfirme(true);
      return;
    }
    envoyer();
  }

  return (
    <form className="panel" onSubmit={soumettre}>
      <div className="field">
        <label htmlFor="pairing-url">{t("peering.form.baseUrl")}</label>
        <input
          id="pairing-url"
          type="text"
          value={baseUrl}
          autoComplete="off"
          onChange={(event) => setBaseUrl(event.target.value)}
        />
        <p className="help">{t("peering.form.baseUrlHelp")}</p>
      </div>
      <div className="field">
        <label htmlFor="pairing-name">{t("peering.form.name")}</label>
        <input
          id="pairing-name"
          type="text"
          value={nom}
          maxLength={80}
          autoComplete="off"
          onChange={(event) => setNom(event.target.value)}
        />
        <p className="help">{t("peering.form.nameHelp")}</p>
      </div>
      {demande.isError && <Refus error={demande.error} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={demande.isPending}>
          {reappariement ? t("peering.form.submitAgain") : t("peering.form.submit")}
        </button>
      </div>
      {confirme && (
        <ConfirmDialog
          title={t("peering.repair.title")}
          confirmLabel={t("peering.repair.confirm")}
          cancelLabel={t("peering.repair.cancel")}
          onCancel={() => setConfirme(false)}
          onConfirm={() => {
            setConfirme(false);
            envoyer();
          }}
        >
          <p>{t("peering.repair.body")}</p>
        </ConfirmDialog>
      )}
    </form>
  );
}
