import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { PageHead } from "../layout/PageHead";

import { type EnrolmentPeer, type PairingState, usePairingState } from "../api/peering";
import { FormulaireDemande } from "./FormulaireDemande";
import { SaisieDuCode } from "./SaisieDuCode";

function Apparie({ peer }: { peer: EnrolmentPeer }) {
  const { t } = useTranslation();
  return (
    <div className="panel">
      <dl className="facts">
        <div>
          <dt className="caption">{t("peering.paired.captionUrl")}</dt>
          <dd className="value">{peer.base_url}</dd>
        </div>
        {/* L'adresse de contact n'apparaît QUE si elle diffère de l'identité : identiques,
            deux lignes feraient chercher une différence qui n'existe pas. Différentes, il
            faut dire pourquoi — sinon l'écran a l'air de se contredire. */}
        {peer.contact_url !== peer.base_url && (
          <div>
            <dt className="caption">{t("peering.paired.captionContact")}</dt>
            <dd className="value">
              {peer.contact_url}
              <div className="row-sub">{t("peering.paired.contactHelp")}</div>
            </dd>
          </div>
        )}
        <div>
          <dt className="caption">{t("peering.paired.captionName")}</dt>
          <dd className="value">
            {peer.declared_name ?? <span className="muted">{t("peering.paired.noName")}</span>}
          </dd>
        </div>
        <div>
          <dt className="caption">{t("peering.paired.captionSince")}</dt>
          <dd className="value">{new Date(peer.created_at).toLocaleString()}</dd>
        </div>
        <div>
          <dt className="caption">{t("peering.paired.captionFingerprint")}</dt>
          <dd className="value">
            <span className="badge">{peer.public_key_fingerprint}</span>
          </dd>
        </div>
      </dl>
    </div>
  );
}

/** Le libellé de l'état courant, et la raison de chacun. */
function Etat({ etat }: { etat: PairingState }) {
  const { t } = useTranslation();
  const classe =
    etat.state === "apparie"
      ? "badge badge-success"
      : etat.state === "en_attente"
        ? "badge badge-accent"
        : etat.state === "non_apparie"
          ? "badge"
          : "badge badge-warning";
  return (
    <p role="status">
      <span className={classe}>{t(`peering.states.${etat.state}`)}</span>
    </p>
  );
}

/**
 * L'écran d'appariement vu du DEMANDEUR : frapper, coller le code, voir où l'on en est.
 *
 * `peerExtra` est le seul endroit où un produit ajoute QUELQUE CHOSE À LUI, et il est
 * rendu sous la ligne du pair parce que ce qu'on y met découle de l'appariement : le
 * module d'environnement y lit l'environnement que l'enrôlement lui assigne. Le module de
 * paramétrage ne passe rien, et c'est l'état normal — ce qu'il recevra, ce sont des
 * connexions git, et cela viendra avec son ticket.
 *
 * Un emplacement et non une liste d'options : un écran qui saurait ce que chaque produit
 * veut afficher porterait la connaissance de ses deux consommateurs, et c'est précisément
 * ce que l'extraction au socle supprime.
 */
export function PairingScreen({ peerExtra }: { peerExtra?: ReactNode } = {}) {
  const { t } = useTranslation();
  const etat = usePairingState();

  if (etat.isPending) {
    return <p role="status">{t("peering.loading")}</p>;
  }
  if (etat.data === undefined) {
    return (
      <p className="alert alert-danger" role="alert">
        {t("peering.errors.unexpected")}
      </p>
    );
  }
  const { state, peer } = etat.data;
  // L'appariement courant reste visible pendant qu'une nouvelle demande attend : c'est le
  // ré-appariement, et remplacer l'un par l'autre avant que l'humain n'ait tranché lui
  // ferait croire que le premier est déjà perdu.
  const enAttente = state === "en_attente" || state === "pair_injoignable";
  const aRecommencer = state === "refusee" || state === "expiree";
  // Le pair refuse nos appels signés alors que nous le croyons apparié : son
  // administrateur a pu révoquer l'appariement. La ligne du pair RESTE affichée, sous un
  // avertissement qui dit que c'est le dernier appariement connu — l'effacer priverait
  // l'humain de l'empreinte qu'il voudra comparer après avoir refrappé.
  const refuseParLePair = state === "refuse_par_le_pair";
  // Le pair l'a DIT, et ses appels nous sont refusés : plus rien à supposer. On nomme la
  // cause et la date, au lieu d'énumérer ce qui aurait pu se passer.
  const revoque = state === "revoque";

  return (
    <section className="section" aria-labelledby="pairing-title">
      <PageHead id="pairing-title" title={t("peering.title")} lead={t("peering.lead")} />
      <div className="card">
        <div className="card-head">
          <h2>{t("peering.current")}</h2>
          <Etat etat={etat.data} />
        </div>
        {peer !== null && <Apparie peer={peer} />}
        {/* Ce que le produit tient EN PLUS du pair, sous la ligne du pair parce que cela
            en découle — et seulement quand il y a un pair : sans appariement, il n'y a rien
            à en tirer. Chez le module d'environnement, c'est l'environnement que
            l'enrôlement lui assigne, dans SA propre requête, pour que l'une puisse échouer
            sans l'autre : « apparié, mais l'environnement n'a pas pu être rafraîchi » est
            précisément ce que l'écran doit pouvoir dire. */}
        {peer !== null && peerExtra}
        {state === "pair_injoignable" && (
          // Distinct d'un refus : faire recommencer pour une panne de réseau détruirait
          // un appariement que quelqu'un est peut-être en train d'accepter.
          <p className="alert" role="status">
            {t("peering.unreachable")}
          </p>
        )}
        {revoque && peer !== null && (
          <p className="alert alert-warning" role="status">
            {t("peering.revoked", {
              date: peer.revoked_at === null ? "" : new Date(peer.revoked_at).toLocaleString(),
            })}
          </p>
        )}
        {refuseParLePair && (
          <p className="alert alert-warning" role="status">
            {t("peering.refusedByPeer")}
          </p>
        )}
        {aRecommencer && (
          <p className="alert" role="status">
            {t(`peering.outcome.${state}`)}
          </p>
        )}
      </div>
      {enAttente && etat.data.attempt !== null ? (
        <div className="card">
          <div className="card-head">
            <h2>{t("peering.pending.title")}</h2>
          </div>
          <SaisieDuCode enrolmentUrl={etat.data.attempt.base_url} />
        </div>
      ) : (
        <div className="card">
          <div className="card-head">
            <h2>{peer === null ? t("peering.form.title") : t("peering.form.titleAgain")}</h2>
          </div>
          <FormulaireDemande reappariement={peer !== null} />
        </div>
      )}
    </section>
  );
}
