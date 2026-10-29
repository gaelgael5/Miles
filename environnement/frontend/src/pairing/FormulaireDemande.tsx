import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";

import { useRequestPairing } from "../api/pairing";
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
        <label htmlFor="pairing-url">{t("pairing.form.baseUrl")}</label>
        <input
          id="pairing-url"
          type="text"
          value={baseUrl}
          autoComplete="off"
          onChange={(event) => setBaseUrl(event.target.value)}
        />
        <p className="help">{t("pairing.form.baseUrlHelp")}</p>
      </div>
      <div className="field">
        <label htmlFor="pairing-name">{t("pairing.form.name")}</label>
        <input
          id="pairing-name"
          type="text"
          value={nom}
          maxLength={80}
          autoComplete="off"
          onChange={(event) => setNom(event.target.value)}
        />
        <p className="help">{t("pairing.form.nameHelp")}</p>
      </div>
      {demande.isError && <Refus error={demande.error} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={demande.isPending}>
          {reappariement ? t("pairing.form.submitAgain") : t("pairing.form.submit")}
        </button>
      </div>
      {confirme && (
        <ConfirmDialog
          title={t("pairing.repair.title")}
          confirmLabel={t("pairing.repair.confirm")}
          cancelLabel={t("pairing.repair.cancel")}
          onCancel={() => setConfirme(false)}
          onConfirm={() => {
            setConfirme(false);
            envoyer();
          }}
        >
          <p>{t("pairing.repair.body")}</p>
        </ConfirmDialog>
      )}
    </form>
  );
}
