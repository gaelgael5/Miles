import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog, PageHead } from "@miles/socle-web";

import {
  type EnvironmentRef,
  type PairedEnvironment,
  type PairingRequest,
  useAttachPeerEnvironment,
  useDesignateRequestEnvironment,
  usePairedEnvironments,
  usePairingRequests,
  useRejectRequest,
} from "../api/pairing";
import { CodeRevele, Duree, resteJusqua, useTicTac } from "./CodeRevele";
import { EnvironmentPicker } from "./EnvironmentPicker";

/**
 * L'environnement rattaché, ou le signal qu'il manque.
 *
 * « À rattacher » porte une pastille d'alerte, et c'est voulu : un appariement sans
 * environnement est un état transitoire HÉRITÉ, pas l'état normal du premier jour — à
 * l'inverse d'un environnement déclaré et pas encore apparié, que le référentiel montre
 * en gris. Les deux absences ne se lisent pas pareil.
 */
function EnvironmentCell({ environnement }: { environnement: EnvironmentRef | null }) {
  const { t } = useTranslation();
  if (environnement === null) {
    return (
      <span className="badge badge-warning">{t("pairing.designation.missing")}</span>
    );
  }
  return (
    <>
      <div>{environnement.label}</div>
      {/* Le slug sous le libellé : c'est lui qui s'écrit dans une procédure, et le
          retrouver sans changer d'écran évite de le recopier de mémoire. */}
      <div className="row-sub">{environnement.slug}</div>
    </>
  );
}


function DemandeRow({ demande }: { demande: PairingRequest }) {
  const { t } = useTranslation();
  const [revele, setRevele] = useState(false);
  const [confirmeRefus, setConfirmeRefus] = useState(false);
  const [ouvreChoix, setOuvreChoix] = useState(false);
  const refus = useRejectRequest();
  const designation = useDesignateRequestEnvironment();
  const maintenant = useTicTac();
  // Révéler le code EST le geste d'acceptation : sans environnement désigné, il n'y a
  // personne à qui rattacher l'appariement, et le serveur refuse. Le bouton suit la même
  // règle — mais il la DIT, au lieu d'être grisé en silence.
  const revelable = demande.environment !== null;

  return (
    <li className="row">
      <div className="row-main">
        {/* Nom déclaré par un tiers non authentifié : React l'échappe, et il n'est
            JAMAIS traité comme un identifiant — c'est l'URL qui en tient lieu. */}
        <div className="row-title">{demande.name ?? t("pairing.requests.unnamed")}</div>
        <div className="row-sub">{demande.base_url}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("pairing.requests.captionReceived")}</div>
        <div className="value">{new Date(demande.created_at).toLocaleString()}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("pairing.requests.captionExpires")}</div>
        <div className="value">
          <Duree secondes={resteJusqua(demande.expires_at, maintenant)} />
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("pairing.designation.caption")}</div>
        <div className="value">
          <EnvironmentCell environnement={demande.environment} />
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("pairing.requests.captionFingerprint")}</div>
        <div className="value">
          <span className="badge">{demande.public_key_fingerprint}</span>
        </div>
      </div>
      <div className="actions row-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={!revelable}
          aria-expanded={revele}
          onClick={() => setRevele((ouvert) => !ouvert)}
        >
          {revele ? t("pairing.requests.hideCode") : t("pairing.requests.showCode")}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          aria-expanded={ouvreChoix}
          onClick={() => setOuvreChoix((ouvert) => !ouvert)}
        >
          {revelable
            ? t("pairing.designation.change")
            : t("pairing.designation.designate")}
        </button>
        <button
          type="button"
          className="btn btn-danger"
          onClick={() => setConfirmeRefus(true)}
        >
          {t("pairing.requests.reject")}
        </button>
      </div>
      {/* La raison du refus est ÉCRITE, pas seulement signifiée par un bouton éteint :
          un bouton grisé muet fait chercher la panne du côté des clés ou du réseau. */}
      {!revelable && (
        <p className="help" role="status">
          {t("pairing.designation.required")}
        </p>
      )}
      {ouvreChoix && (
        <EnvironmentPicker
          choisi={demande.environment?.id ?? null}
          pending={designation.isPending}
          error={designation.isError ? designation.error : null}
          submitLabel={t("pairing.designation.submit")}
          onChoose={(environmentId) =>
            designation.mutate(
              { baseUrl: demande.base_url, environmentId },
              { onSuccess: () => setOuvreChoix(false) },
            )
          }
        />
      )}
      {revele && revelable && <CodeRevele baseUrl={demande.base_url} />}
      {/* Le refus détruit le secret de la demande : un clic isolé ne doit pas suffire. */}
      {confirmeRefus && (
        <ConfirmDialog
          title={t("pairing.reject.title")}
          confirmLabel={t("pairing.reject.confirm")}
          cancelLabel={t("pairing.reject.cancel")}
          onCancel={() => setConfirmeRefus(false)}
          onConfirm={() => {
            refus.mutate(demande.base_url);
            setConfirmeRefus(false);
          }}
        >
          <p>{t("pairing.reject.body", { url: demande.base_url })}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

function ApparieRow({ environnement }: { environnement: PairedEnvironment }) {
  const { t } = useTranslation();
  const [ouvreChoix, setOuvreChoix] = useState(false);
  const rattachement = useAttachPeerEnvironment();
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
      {aRattacher && (
        <div className="actions row-actions">
          <button
            type="button"
            className="btn btn-primary"
            aria-expanded={ouvreChoix}
            onClick={() => setOuvreChoix((ouvert) => !ouvert)}
          >
            {t("pairing.designation.attach")}
          </button>
        </div>
      )}
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
    </li>
  );
}

export function PairingScreen() {
  const { t } = useTranslation();
  const demandes = usePairingRequests();
  const apparies = usePairedEnvironments();

  return (
    <section className="section" aria-labelledby="pairing-title">
      <PageHead
        id="pairing-title"
        title={t("pairing.title")}
        lead={t("pairing.lead")}
      />
      <div className="card">
        <div className="card-head">
          <h2>{t("pairing.requests.title")}</h2>
        </div>
        <p className="help">{t("pairing.requests.help")}</p>
        {demandes.isPending && <p role="status">{t("pairing.loading")}</p>}
        {demandes.isError && (
          <p className="alert alert-danger" role="alert">
            {t("pairing.error")}
          </p>
        )}
        {demandes.data?.length === 0 && (
          // État vide NEUTRE : aucune demande en attente n'est pas un problème.
          <p className="muted" role="status">
            {t("pairing.requests.empty")}
          </p>
        )}
        <ul className="card-list">
          {demandes.data?.map((demande) => (
            <DemandeRow key={demande.base_url} demande={demande} />
          ))}
        </ul>
      </div>
      <div className="card">
        <div className="card-head">
          <h2>{t("pairing.paired.title")}</h2>
        </div>
        {apparies.data?.length === 0 && (
          <p className="muted" role="status">
            {t("pairing.paired.empty")}
          </p>
        )}
        <ul className="card-list">
          {apparies.data?.map((environnement) => (
            <ApparieRow key={environnement.base_url} environnement={environnement} />
          ))}
        </ul>
      </div>
    </section>
  );
}
