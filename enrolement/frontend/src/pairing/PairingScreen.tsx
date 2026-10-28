import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog, CopyButton, PageHead } from "@miles/socle-web";

import {
  type PairedEnvironment,
  type PairingRequest,
  usePairedEnvironments,
  usePairingCode,
  usePairingRequests,
  useRejectRequest,
} from "../api/pairing";

/** Secondes restantes avant un instant donné, jamais négatives. */
function resteJusqua(instant: string, maintenant: number): number {
  return Math.max(0, Math.round((Date.parse(instant) - maintenant) / 1000));
}

/**
 * Une horloge qui bat à la seconde, pour les comptes à rebours affichés.
 *
 * Locale et uniquement pour l'AFFICHAGE : ce qui décide de l'acceptation d'un code est
 * l'horloge du serveur, et les deux n'ont aucune raison de s'accorder. Afficher un compte
 * à rebours dérivé du serveur à chaque seconde coûterait une requête par seconde.
 */
function useTicTac(): number {
  const [maintenant, setMaintenant] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setMaintenant(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return maintenant;
}

function Duree({ secondes }: { secondes: number }) {
  const { t } = useTranslation();
  const minutes = Math.floor(secondes / 60);
  // Trois échelles, parce que la durée de vie d'une demande est PARAMÉTRABLE : une heure
  // par défaut, sept jours au plus. « dans 10080 min » est exact et illisible.
  const libelle =
    minutes >= 60
      ? t("pairing.requests.expiresInHours", { n: Math.round(minutes / 60) })
      : minutes >= 1
        ? t("pairing.requests.expiresInMinutes", { n: minutes })
        : t("pairing.requests.expiresInSeconds", { n: secondes });
  return <span className={secondes === 0 ? "badge badge-warning" : "badge"}>{libelle}</span>;
}

/**
 * Le code à recopier, et ce qu'il reste de sa fenêtre.
 *
 * Il n'est ni imprimable, ni téléchargeable, ni exportable : la seule sortie offerte est
 * le presse-papiers. Le rendre exportable en ferait un secret qui traîne, alors qu'il est
 * conçu pour ne valoir que quelques secondes et qu'une fois.
 */
function CodeRevele({ baseUrl }: { baseUrl: string }) {
  const { t } = useTranslation();
  const code = usePairingCode(baseUrl);
  const maintenant = useTicTac();
  const [lu, setLu] = useState(() => Date.now());

  useEffect(() => {
    if (code.data !== undefined) {
      setLu(Date.now());
    }
  }, [code.data]);

  if (code.isPending) {
    return <p role="status">{t("pairing.code.loading")}</p>;
  }
  if (code.data === undefined) {
    // Le plus souvent : la demande vient d'expirer ou d'être refusée ailleurs. Le dire
    // vaut mieux qu'afficher un code vide que quelqu'un recopierait.
    return (
      <p className="alert" role="status">
        {t("pairing.code.gone")}
      </p>
    );
  }
  // Borné par ce que le SERVEUR a dit : l'effet qui pose `lu` s'exécute après le rendu,
  // donc l'écart peut être très légèrement négatif et faire afficher une seconde de plus
  // que ce qu'il reste. Mieux vaut annoncer un peu moins qu'un peu trop.
  const reste = Math.min(
    code.data.seconds_remaining,
    Math.max(0, code.data.seconds_remaining - Math.floor((maintenant - lu) / 1000)),
  );
  return (
    <div className="row-detail">
      <p className="help">{t("pairing.code.handOver")}</p>
      {/* `actions` et non `facts` : `facts` est une grille à deux colonnes pour des
          couples légende/valeur, et le bouton de copie s'y étirait sur toute la largeur
          de la seconde colonne. Ici trois éléments se suivent sur une ligne. */}
      <div className="actions">
        <div className="code-block code-large" aria-label={t("pairing.code.label")}>
          {code.data.code}
        </div>
        <CopyButton text={code.data.code} label={t("pairing.code.copy")} />
        <span className={reste <= 5 ? "badge badge-warning" : "badge"} role="timer">
          {t("pairing.code.renewsIn", { n: reste })}
        </span>
      </div>
      <p className="help">{t("pairing.code.perishable")}</p>
    </div>
  );
}

function DemandeRow({ demande }: { demande: PairingRequest }) {
  const { t } = useTranslation();
  const [revele, setRevele] = useState(false);
  const [confirmeRefus, setConfirmeRefus] = useState(false);
  const refus = useRejectRequest();
  const maintenant = useTicTac();

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
        <div className="caption">{t("pairing.requests.captionFingerprint")}</div>
        <div className="value">
          <span className="badge">{demande.public_key_fingerprint}</span>
        </div>
      </div>
      <div className="actions row-actions">
        <button
          type="button"
          className="btn btn-primary"
          aria-expanded={revele}
          onClick={() => setRevele((ouvert) => !ouvert)}
        >
          {revele ? t("pairing.requests.hideCode") : t("pairing.requests.showCode")}
        </button>
        <button
          type="button"
          className="btn btn-danger"
          onClick={() => setConfirmeRefus(true)}
        >
          {t("pairing.requests.reject")}
        </button>
      </div>
      {revele && <CodeRevele baseUrl={demande.base_url} />}
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
  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{environnement.name ?? t("pairing.requests.unnamed")}</div>
        <div className="row-sub">{environnement.base_url}</div>
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
