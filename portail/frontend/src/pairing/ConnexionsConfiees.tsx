import { useTranslation } from "react-i18next";

import { useConfidingState, useTransmitConfided } from "../api/confiage";

/**
 * Les connexions git confiées au module d'enrôlement, et l'état de leur transmission.
 *
 * Rendu sous la ligne du pair par `peerExtra`, parce que ce qu'on y lit DÉCOULE de
 * l'appariement : sans pair, il n'y a personne à qui confier.
 *
 * Trois états, et les trois se lisent différemment — c'est pourquoi `up_to_date` est
 * porté par la réponse au lieu d'être déduit de la présence d'une date :
 *
 * - transmis et à jour : il détient ce que nous avons ;
 * - jamais transmis : apparié, mais rien n'est encore parti ;
 * - transmis et PÉRIMÉ : il détient une photo plus ancienne. C'est le cas qu'il faut
 *   nommer — une transmission a échoué, et sans ce mot l'écran dirait « confiées » pour
 *   quelque chose qui n'est jamais arrivé.
 *
 * Aucun credential n'est affiché, et il n'y a pas de champ pour en afficher un : le
 * nombre de connexions et la date de transmission sont tout ce qu'on peut en dire.
 */
export function ConnexionsConfiees() {
  const { t } = useTranslation();
  const etat = useConfidingState();
  const transmettre = useTransmitConfided();

  if (etat.isPending) {
    return <p role="status">{t("confiding.loading")}</p>;
  }
  if (etat.data === undefined) {
    return (
      <p className="alert" role="status">
        {t("confiding.unavailable")}
      </p>
    );
  }

  const { transmitted_at: transmis, up_to_date: aJour, connections, revision } = etat.data;
  return (
    <div className="panel">
      <dl className="facts">
        <div>
          <dt className="caption">{t("confiding.caption")}</dt>
          <dd className="value">
            {t("confiding.count", { count: connections })}
            <div className="row-sub">{t("confiding.help")}</div>
          </dd>
        </div>
        {transmis !== null && (
          <div>
            <dt className="caption">{t("confiding.captionTransmitted")}</dt>
            <dd className="value">
              {new Date(transmis).toLocaleString()}
              <span className="badge">{t("confiding.revision", { revision })}</span>
            </dd>
          </div>
        )}
      </dl>
      {transmis === null && (
        <p className="alert" role="status">
          {t("confiding.never")}
        </p>
      )}
      {transmis !== null && !aJour && (
        <p className="alert alert-warning" role="status">
          {t("confiding.stale")}
        </p>
      )}
      {/* Le bouton est TOUJOURS là, même à jour : retransmettre est sans effet de bord
          observable — l'état complet est idempotent —, et le cacher priverait d'un geste
          celui qui doute de ce que l'autre bout détient. */}
      <button
        type="button"
        className="btn"
        onClick={() => transmettre.mutate()}
        disabled={transmettre.isPending}
      >
        {t("confiding.transmit")}
      </button>
      {transmettre.isError && (
        <p className="alert alert-danger" role="alert">
          {t("confiding.refused")}
        </p>
      )}
    </div>
  );
}
