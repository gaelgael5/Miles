import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, ConfirmDialog, PageHead } from "@miles/socle-web";

import {
  clockDrift,
  type EnrolmentPeer,
  type PairingState,
  useCancelPairing,
  useConfirmPairing,
  usePairingState,
  useRequestPairing,
} from "../api/pairing";

/**
 * La clef de libellé d'un refus, choisie sur ce que le serveur a RÉELLEMENT dit.
 *
 * Les cas sont séparés parce qu'ils appellent des gestes différents : une URL malformée
 * se corrige dans le champ, une URL qui ne répond pas se vérifie ailleurs, et un code
 * refusé se ressaisit. Les fondre en « une erreur est survenue » ferait recommencer au
 * hasard — ce que le ticket interdit explicitement.
 */
function refusKey(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "pairing.errors.unexpected";
  }
  if (error.status === 422) {
    return error.detail === "name" ? "pairing.errors.name" : "pairing.errors.baseUrl";
  }
  if (error.status === 502) {
    return "pairing.errors.unreachable";
  }
  if (error.status === 409) {
    return "pairing.errors.refused";
  }
  return "pairing.errors.unexpected";
}

function Refus({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const derive = clockDrift(error);
  return (
    <p className="alert alert-danger" role="alert">
      {/* La dérive d'horloge est le SEUL refus que le pair détaille, et il le fait parce
          qu'un appariement TOTP qui échoue sans dire pourquoi est le piège classique :
          on cherche du côté du code pendant que la cause est une machine à l'heure près. */}
      {derive === null
        ? t(refusKey(error))
        : t("pairing.errors.clockSkew", { seconds: Math.abs(derive) })}
    </p>
  );
}

function FormulaireDemande({ reappariement }: { reappariement: boolean }) {
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

function SaisieDuCode({ enrolmentUrl }: { enrolmentUrl: string }) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const confirmation = useConfirmPairing();
  const annulation = useCancelPairing();

  return (
    <div className="panel">
      <p className="help">{t("pairing.pending.where", { url: enrolmentUrl })}</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          confirmation.mutate(code, { onSuccess: () => setCode("") });
        }}
      >
        <div className="field">
          <label htmlFor="pairing-code">{t("pairing.pending.codeLabel")}</label>
          <input
            id="pairing-code"
            type="text"
            value={code}
            autoComplete="off"
            inputMode="numeric"
            onChange={(event) => setCode(event.target.value)}
          />
          {/* Le code arrive par copier-coller : espaces et retours à la ligne sont
              nettoyés avant l'envoi, pas refusés. */}
          <p className="help">{t("pairing.pending.codeHelp")}</p>
        </div>
        {confirmation.isError && <Refus error={confirmation.error} />}
        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={confirmation.isPending}>
            {t("pairing.pending.submit")}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => annulation.mutate()}
          >
            {t("pairing.pending.cancel")}
          </button>
        </div>
      </form>
    </div>
  );
}

function Apparie({ peer }: { peer: EnrolmentPeer }) {
  const { t } = useTranslation();
  return (
    <div className="panel">
      <dl className="facts">
        <div>
          <dt className="caption">{t("pairing.paired.captionUrl")}</dt>
          <dd className="value">{peer.base_url}</dd>
        </div>
        {/* L'adresse de contact n'apparaît QUE si elle diffère de l'identité : identiques,
            deux lignes feraient chercher une différence qui n'existe pas. Différentes, il
            faut dire pourquoi — sinon l'écran a l'air de se contredire. */}
        {peer.contact_url !== peer.base_url && (
          <div>
            <dt className="caption">{t("pairing.paired.captionContact")}</dt>
            <dd className="value">
              {peer.contact_url}
              <div className="row-sub">{t("pairing.paired.contactHelp")}</div>
            </dd>
          </div>
        )}
        <div>
          <dt className="caption">{t("pairing.paired.captionName")}</dt>
          <dd className="value">
            {peer.declared_name ?? <span className="muted">{t("pairing.paired.noName")}</span>}
          </dd>
        </div>
        <div>
          <dt className="caption">{t("pairing.paired.captionSince")}</dt>
          <dd className="value">{new Date(peer.created_at).toLocaleString()}</dd>
        </div>
        <div>
          <dt className="caption">{t("pairing.paired.captionFingerprint")}</dt>
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
      <span className={classe}>{t(`pairing.states.${etat.state}`)}</span>
    </p>
  );
}

export function PairingScreen() {
  const { t } = useTranslation();
  const etat = usePairingState();

  if (etat.isPending) {
    return <p role="status">{t("pairing.loading")}</p>;
  }
  if (etat.data === undefined) {
    return (
      <p className="alert alert-danger" role="alert">
        {t("pairing.errors.unexpected")}
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

  return (
    <section className="section" aria-labelledby="pairing-title">
      <PageHead id="pairing-title" title={t("pairing.title")} lead={t("pairing.lead")} />
      <div className="card">
        <div className="card-head">
          <h2>{t("pairing.current")}</h2>
          <Etat etat={etat.data} />
        </div>
        {peer !== null && <Apparie peer={peer} />}
        {state === "pair_injoignable" && (
          // Distinct d'un refus : faire recommencer pour une panne de réseau détruirait
          // un appariement que quelqu'un est peut-être en train d'accepter.
          <p className="alert" role="status">
            {t("pairing.unreachable")}
          </p>
        )}
        {refuseParLePair && (
          <p className="alert alert-warning" role="status">
            {t("pairing.refusedByPeer")}
          </p>
        )}
        {aRecommencer && (
          <p className="alert" role="status">
            {t(`pairing.outcome.${state}`)}
          </p>
        )}
      </div>
      {enAttente && etat.data.attempt !== null ? (
        <div className="card">
          <div className="card-head">
            <h2>{t("pairing.pending.title")}</h2>
          </div>
          <SaisieDuCode enrolmentUrl={etat.data.attempt.base_url} />
        </div>
      ) : (
        <div className="card">
          <div className="card-head">
            <h2>{peer === null ? t("pairing.form.title") : t("pairing.form.titleAgain")}</h2>
          </div>
          <FormulaireDemande reappariement={peer !== null} />
        </div>
      )}
    </section>
  );
}
