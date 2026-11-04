import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { type PairedEnvironment, useSetPeerContactUrl } from "../api/pairing";

/**
 * L'adresse où ce module JOINT une stack, et de quoi la corriger.
 *
 * Elle n'est montrée en lecture que si elle diffère de l'identité : identiques, deux
 * lignes feraient chercher une différence qui n'existe pas. Le bouton, lui, est toujours
 * là — c'est par lui qu'on la rend différente le jour où un intermédiaire s'interpose, et
 * un réglage qu'on ne peut atteindre qu'une fois le problème survenu n'aide personne.
 */
export function ContactUrlForm({ environnement }: { environnement: PairedEnvironment }) {
  const { t } = useTranslation();
  const champ = useId();
  const [ouvert, setOuvert] = useState(false);
  const [saisie, setSaisie] = useState(environnement.contact_url);
  const changement = useSetPeerContactUrl();
  const distincte = environnement.contact_url !== environnement.base_url;

  return (
    <>
      {distincte && (
        <div className="cell">
          <div className="caption">{t("pairing.paired.contactCaption")}</div>
          <div className="value">{environnement.contact_url}</div>
        </div>
      )}
      <div className="actions row-actions">
        <button
          type="button"
          className="btn btn-secondary"
          aria-expanded={ouvert}
          onClick={() => setOuvert((o) => !o)}
        >
          {t("pairing.paired.contactEdit")}
        </button>
      </div>
      {ouvert && (
        <form
          className="form"
          onSubmit={(evenement) => {
            evenement.preventDefault();
            changement.mutate(
              { baseUrl: environnement.base_url, contactUrl: saisie },
              { onSuccess: () => setOuvert(false) },
            );
          }}
        >
          <div className="field">
            <label htmlFor={champ}>{t("pairing.paired.contactLabel")}</label>
            <input
              id={champ}
              type="text"
              value={saisie}
              onChange={(evenement) => setSaisie(evenement.target.value)}
            />
          </div>
          <p className="help">{t("pairing.paired.contactHelp")}</p>
          {changement.isError && (
            <p className="alert alert-danger" role="alert">
              {t("pairing.paired.contactError")}
            </p>
          )}
          <button type="submit" className="btn btn-primary" disabled={changement.isPending}>
            {t("pairing.paired.contactSubmit")}
          </button>
        </form>
      )}
    </>
  );
}
