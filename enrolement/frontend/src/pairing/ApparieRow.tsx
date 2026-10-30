import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";

import { type PairedEnvironment, useRevokePeer } from "../api/pairing";
import { ContactUrlForm } from "./ContactUrlForm";
import { EnvironmentAssign } from "./EnvironmentAssign";
import { EnvironmentCell } from "./EnvironmentCell";

/**
 * Ce que la révocation va provoquer sur le parc, écrit AVANT qu'on la provoque.
 *
 * Le nombre de devices est la seule chose qui rende ce geste décidable, et c'est pour
 * cela qu'il est dans la confirmation et non dans une aide à côté. Quand il est inconnu
 * — le référentiel des devices n'existe pas encore —, on le DIT : afficher « 0 devices
 * seront remis en attente » serait une affirmation fausse sur l'état du parc, et c'est
 * précisément sur cette phrase que l'humain déciderait.
 */
function Consequence({ devices }: { devices: number | null }) {
  const { t } = useTranslation();
  if (devices === null) {
    return <p className="help">{t("pairing.revoke.devicesUnknown")}</p>;
  }
  return <p className="help">{t("pairing.revoke.devices", { count: devices })}</p>;
}

export function ApparieRow({ environnement }: { environnement: PairedEnvironment }) {
  const { t } = useTranslation();
  const [confirmeRevocation, setConfirmeRevocation] = useState(false);
  const revocation = useRevokePeer();
  // L'espèce commande ce que cette ligne a du sens à montrer. Le module de paramétrage ne
  // reçoit pas de devices : lui afficher « à rattacher » et un compte de devices
  // réclamerait un geste qui n'existe pas pour lui, et offrirait un choix que le serveur
  // refuse. On suit donc l'espèce, jamais l'absence de valeur.
  const rattachable = environnement.species === "environnement";
  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{environnement.name ?? t("pairing.requests.unnamed")}</div>
        <div className="row-sub">{environnement.base_url}</div>
      </div>
      {rattachable && (
        <div className="cell">
          <div className="caption">{t("pairing.designation.caption")}</div>
          <div className="value">
            <EnvironmentCell environnement={environnement.environment} />
          </div>
        </div>
      )}
      <div className="cell">
        <div className="caption">{t("pairing.paired.captionSince")}</div>
        <div className="value">{new Date(environnement.created_at).toLocaleString()}</div>
      </div>
      {rattachable && (
        <div className="cell">
          <div className="caption">{t("pairing.paired.captionDevices")}</div>
          {/* « — » et non « 0 » : le référentiel des devices n'existe pas encore, et un
              zéro se lirait « aucun device » sur un écran qui ne sait pas compter. */}
          <div className="value">
            {environnement.device_count === null ? (
              <span className="muted" title={t("pairing.paired.devicesUnknownHelp")}>
                {t("pairing.paired.devicesUnknown")}
              </span>
            ) : (
              environnement.device_count
            )}
          </div>
        </div>
      )}
      <div className="cell">
        <div className="caption">{t("pairing.requests.captionFingerprint")}</div>
        <div className="value">
          <span className="badge">{environnement.public_key_fingerprint}</span>
        </div>
      </div>
      <ContactUrlForm environnement={environnement} />
      {rattachable && <EnvironmentAssign environnement={environnement} />}
      <div className="actions row-actions">
        <button
          type="button"
          className="btn btn-danger"
          onClick={() => setConfirmeRevocation(true)}
        >
          {t("pairing.revoke.action")}
        </button>
      </div>
      {revocation.isError && (
        <p className="alert alert-danger" role="alert">
          {t("pairing.revoke.error")}
        </p>
      )}
      {/* La révocation détruit la clé du pair et libère ses devices : un clic isolé ne
          doit pas suffire, et la confirmation doit NOMMER les deux conséquences. */}
      {confirmeRevocation && (
        <ConfirmDialog
          title={t("pairing.revoke.title")}
          confirmLabel={t("pairing.revoke.confirm")}
          cancelLabel={t("pairing.revoke.cancel")}
          onCancel={() => setConfirmeRevocation(false)}
          onConfirm={() => {
            revocation.mutate(environnement.base_url);
            setConfirmeRevocation(false);
          }}
        >
          <p>
            {!rattachable
              ? t("pairing.revoke.bodyParametrage", { url: environnement.base_url })
              : environnement.environment === null
                ? t("pairing.revoke.bodyUnattached", { url: environnement.base_url })
                : t("pairing.revoke.body", {
                    url: environnement.base_url,
                    label: environnement.environment.label,
                    slug: environnement.environment.slug,
                  })}
          </p>
          {/* Les devices ne concernent que les environnements. Pour le module de
              paramétrage, la conséquence est d'un autre ordre — ce qui lui avait été
              confié cesse de l'être — et elle se dit avec ses propres mots. */}
          {rattachable ? (
            <Consequence devices={environnement.device_count} />
          ) : (
            <p className="help">{t("pairing.revoke.parametrageConfided")}</p>
          )}
          <p className="help">{t("pairing.revoke.keys")}</p>
          {rattachable && environnement.environment !== null && (
            <p className="help">{t("pairing.revoke.environmentKept")}</p>
          )}
        </ConfirmDialog>
      )}
    </li>
  );
}
