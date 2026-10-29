import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";

import {
  type PairedEnvironment,
  useAttachPeerEnvironment,
  useRevokePeer,
} from "../api/pairing";
import { EnvironmentCell } from "./EnvironmentCell";
import { EnvironmentPicker } from "./EnvironmentPicker";

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
  const [ouvreChoix, setOuvreChoix] = useState(false);
  const [confirmeRevocation, setConfirmeRevocation] = useState(false);
  const rattachement = useAttachPeerEnvironment();
  const revocation = useRevokePeer();
  // Un appariement conclu AVANT que la désignation n'existe. Il ne se rattache qu'une
  // fois : l'en changer déplacerait ses devices sans le dire, et ce geste s'appelle
  // révoquer puis réapparier.
  const aRattacher = environnement.environment === null;
  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{environnement.name ?? t("pairing.requests.unnamed")}</div>
        <div className="row-sub">{environnement.base_url}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("pairing.designation.caption")}</div>
        <div className="value">
          <EnvironmentCell environnement={environnement.environment} />
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("pairing.paired.captionSince")}</div>
        <div className="value">{new Date(environnement.created_at).toLocaleString()}</div>
      </div>
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
      <div className="cell">
        <div className="caption">{t("pairing.requests.captionFingerprint")}</div>
        <div className="value">
          <span className="badge">{environnement.public_key_fingerprint}</span>
        </div>
      </div>
      <div className="actions row-actions">
        {aRattacher && (
          <button
            type="button"
            className="btn btn-primary"
            aria-expanded={ouvreChoix}
            onClick={() => setOuvreChoix((ouvert) => !ouvert)}
          >
            {t("pairing.designation.attach")}
          </button>
        )}
        <button
          type="button"
          className="btn btn-danger"
          onClick={() => setConfirmeRevocation(true)}
        >
          {t("pairing.revoke.action")}
        </button>
      </div>
      {aRattacher && !ouvreChoix && (
        <p className="help" role="status">
          {t("pairing.designation.attachHelp")}
        </p>
      )}
      {ouvreChoix && (
        <EnvironmentPicker
          choisi={null}
          pending={rattachement.isPending}
          error={rattachement.isError ? rattachement.error : null}
          submitLabel={t("pairing.designation.attachSubmit")}
          onChoose={(environmentId) =>
            rattachement.mutate(
              { baseUrl: environnement.base_url, environmentId },
              { onSuccess: () => setOuvreChoix(false) },
            )
          }
        />
      )}
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
            {environnement.environment === null
              ? t("pairing.revoke.bodyUnattached", { url: environnement.base_url })
              : t("pairing.revoke.body", {
                  url: environnement.base_url,
                  label: environnement.environment.label,
                  slug: environnement.environment.slug,
                })}
          </p>
          <Consequence devices={environnement.device_count} />
          <p className="help">{t("pairing.revoke.keys")}</p>
          {environnement.environment !== null && (
            <p className="help">{t("pairing.revoke.environmentKept")}</p>
          )}
        </ConfirmDialog>
      )}
    </li>
  );
}
