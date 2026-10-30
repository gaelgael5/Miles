import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type ConfidedConnection,
  useConfidedGitConnection,
  useConfidedGitConnections,
} from "../api/confiedGit";

/** Le credential, éprouvé ICI : s'ouvre-t-il encore avec la clé de cette instance ? */
function Credential({ connectionId }: { connectionId: string }) {
  const { t } = useTranslation();
  const detail = useConfidedGitConnection(connectionId, true);

  if (detail.isPending) {
    return <p role="status">{t("pairing.confided.checking")}</p>;
  }
  if (detail.data === undefined) {
    return (
      <p className="alert" role="status">
        {t("pairing.confided.checkFailed")}
      </p>
    );
  }
  // Le seul diagnostic possible sans lire git — et lire git est le relais, reporté. Dit
  // comme un problème de CREDENTIAL, parce que c'est ce qu'il faut distinguer d'une
  // panne de forge : sans ce mot, le diagnostic part sur la configuration de
  // l'environnement.
  return detail.data.credential_readable ? (
    <p className="help" role="status">
      {t("pairing.confided.readable")}
    </p>
  ) : (
    <p className="alert alert-danger" role="alert">
      {t("pairing.confided.unreadable")}
    </p>
  );
}

function ConnexionRow({ connexion }: { connexion: ConfidedConnection }) {
  const { t } = useTranslation();
  const [verifie, setVerifie] = useState(false);

  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{connexion.label}</div>
        <div className="row-sub">{connexion.base_url}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("pairing.confided.captionWorkspaces")}</div>
        <div className="value">
          {connexion.workspaces.length === 0 ? (
            <span className="muted">{t("pairing.confided.noWorkspace")}</span>
          ) : (
            connexion.workspaces.map((workspace) => (
              <div key={workspace.id}>
                {workspace.id}
                {/* Le dépôt sous le workspace : c'est le couple qui sert à lire git, et
                    séparer les deux obligerait à les rapprocher de mémoire. */}
                <div className="row-sub">
                  {workspace.repo_url ?? t("pairing.confided.noRepo")}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("pairing.confided.captionSince")}</div>
        <div className="value">{new Date(connexion.confided_at).toLocaleString()}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("pairing.confided.captionRenewed")}</div>
        <div className="value">
          {connexion.renewed_at === null ? (
            // JAMAIS renouvelé, et ce n'est pas une absence de donnée : c'est l'état
            // normal d'une connexion confiée une fois et pas retouchée depuis.
            <span className="muted">{t("pairing.confided.neverRenewed")}</span>
          ) : (
            new Date(connexion.renewed_at).toLocaleString()
          )}
        </div>
      </div>
      <div className="actions row-actions">
        <button
          type="button"
          className="btn btn-secondary"
          aria-expanded={verifie}
          onClick={() => setVerifie((ouvert) => !ouvert)}
        >
          {t("pairing.confided.check")}
        </button>
      </div>
      {verifie && <Credential connectionId={connexion.id} />}
    </li>
  );
}

/**
 * Ce que ce module détient pour le compte du module de paramétrage.
 *
 * Trois états, et les trois se lisent différemment : aucun module de paramétrage apparié
 * — il n'y a personne à qui on puisse confier quoi que ce soit —, apparié mais rien de
 * reçu, et des connexions détenues. Le premier est le critère 7 du ticket : il se DIT, au
 * lieu de montrer une liste vide qui se lirait comme une panne de la forge.
 */
export function ConnexionsConfiees() {
  const { t } = useTranslation();
  const etat = useConfidedGitConnections();

  return (
    <div className="card">
      <div className="card-head">
        <h2>{t("pairing.confided.title")}</h2>
      </div>
      <p className="help">{t("pairing.confided.help")}</p>
      {etat.isPending && <p role="status">{t("pairing.loading")}</p>}
      {etat.isError && (
        <p className="alert alert-danger" role="alert">
          {t("pairing.confided.error")}
        </p>
      )}
      {etat.data !== undefined && etat.data.peer_base_url === null && (
        <p className="alert" role="status">
          {t("pairing.confided.noParametrage")}
        </p>
      )}
      {etat.data?.peer_base_url !== null && etat.data?.connections.length === 0 && (
        <p className="muted" role="status">
          {t("pairing.confided.empty")}
        </p>
      )}
      {etat.data?.received_at !== null && etat.data !== undefined && (
        <dl className="facts">
          <div>
            <dt className="caption">{t("pairing.confided.captionReceived")}</dt>
            <dd className="value">
              {new Date(etat.data.received_at as string).toLocaleString()}
              <span className="badge">
                {t("pairing.confided.revision", { revision: etat.data.revision })}
              </span>
            </dd>
          </div>
        </dl>
      )}
      <ul className="card-list">
        {etat.data?.connections.map((connexion) => (
          <ConnexionRow key={connexion.id} connexion={connexion} />
        ))}
      </ul>
    </div>
  );
}
