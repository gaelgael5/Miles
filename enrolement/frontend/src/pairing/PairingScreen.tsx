import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog, PageHead } from "@miles/socle-web";

import {
  type PairingRequest,
  useDesignateRequestEnvironment,
  usePairedEnvironments,
  usePairingRequests,
  useRejectRequest,
} from "../api/pairing";
import { ApparieRow } from "./ApparieRow";
import { ConnexionsConfiees } from "./ConnexionsConfiees";
import { CodeRevele, Duree, resteJusqua, useTicTac } from "./CodeRevele";
import { EnvironmentCell } from "./EnvironmentCell";
import { EspeceBadge } from "./EspeceBadge";
import { EnvironmentPicker } from "./EnvironmentPicker";

function DemandeRow({ demande }: { demande: PairingRequest }) {
  const { t } = useTranslation();
  const [revele, setRevele] = useState(false);
  const [confirmeRefus, setConfirmeRefus] = useState(false);
  const [ouvreChoix, setOuvreChoix] = useState(false);
  const refus = useRejectRequest();
  const designation = useDesignateRequestEnvironment();
  const maintenant = useTicTac();
  // Un environnement se rattache à un environnement du référentiel ; le module de
  // paramétrage ne reçoit pas de devices, et il n'y a rien à lui désigner. L'écran suit
  // l'espèce plutôt que l'absence de valeur : lue seule, une désignation nulle ferait
  // réclamer un rattachement à qui n'en a pas besoin, et son code resterait caché.
  const rattachable = demande.species === "environnement";
  // Révéler le code EST le geste d'acceptation : sans environnement désigné, il n'y a
  // personne à qui rattacher l'appariement, et le serveur refuse. Le bouton suit la même
  // règle — mais il la DIT, au lieu d'être grisé en silence.
  const revelable = !rattachable || demande.environment !== null;

  return (
    <li className="row">
      <div className="row-main">
        {/* Nom déclaré par un tiers non authentifié : React l'échappe, et il n'est
            JAMAIS traité comme un identifiant — c'est l'URL qui en tient lieu. */}
        <div className="row-title">{demande.name ?? t("pairing.requests.unnamed")}</div>
        <div className="row-sub">{demande.base_url}</div>
      </div>
      {/* AVANT la date et l'empreinte, et c'est volontaire : c'est la première chose à
          lire pour décider, pas un détail de la ligne. */}
      <div className="cell">
        <div className="caption">{t("pairing.species.caption")}</div>
        <div className="value">
          <EspeceBadge species={demande.species} />
        </div>
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
      {rattachable && (
        <div className="cell">
          <div className="caption">{t("pairing.designation.caption")}</div>
          <div className="value">
            <EnvironmentCell environnement={demande.environment} />
          </div>
        </div>
      )}
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
        {rattachable && (
          <button
            type="button"
            className="btn btn-secondary"
            aria-expanded={ouvreChoix}
            onClick={() => setOuvreChoix((ouvert) => !ouvert)}
          >
            {demande.environment !== null
              ? t("pairing.designation.change")
              : t("pairing.designation.designate")}
          </button>
        )}
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
      {ouvreChoix && rattachable && (
        <EnvironmentPicker
          choisi={demande.environment?.id ?? null}
          pending={designation.isPending}
          error={designation.isError ? designation.error : null}
          submitLabel={t("pairing.designation.submit")}
          onChoose={(choisi) =>
            designation.mutate(
              { baseUrl: demande.base_url, environmentId: choisi.id },
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
      {/* APRÈS les appariés, et c'est l'ordre de lecture : ce qu'on détient découle de
          l'appariement du module de paramétrage, qui est dans la liste ci-dessus. */}
      <ConnexionsConfiees />
    </section>
  );
}
