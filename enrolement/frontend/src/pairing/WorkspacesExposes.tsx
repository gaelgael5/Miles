import { useTranslation } from "react-i18next";

import { useExposedWorkspaces } from "../api/confiedGit";

/**
 * Les workspaces que le module de paramétrage apparié nous expose.
 *
 * DANS le bloc du module de paramétrage, et c'est tout le propos (Gael, 01/11/2026) :
 * c'est ce serveur-là qui nous les expose, et les montrer ailleurs laissait croire qu'ils
 * venaient d'ici. Le bloc des connexions git a disparu de cet écran avec ce déplacement :
 * la forge, le dépôt et le credential sont l'affaire du module de paramétrage, qui les a
 * saisis, et les répéter ici donnait un second endroit où les lire — donc un second
 * endroit à croire quand les deux divergent.
 */
export function WorkspacesExposes() {
  const { t } = useTranslation();
  const expose = useExposedWorkspaces();

  if (expose.isPending) {
    return <p role="status">{t("pairing.loading")}</p>;
  }
  if (expose.isError) {
    return (
      <p className="alert alert-danger" role="alert">
        {t("pairing.workspaces.error")}
      </p>
    );
  }
  if (expose.workspaces.length === 0) {
    // Apparié mais rien de confié : c'est l'état du premier jour, pas une panne. Le
    // dire évite de chercher du côté de la forge.
    return (
      <p className="muted" role="status">
        {t("pairing.workspaces.empty")}
      </p>
    );
  }
  return (
    <div className="cell">
      <div className="caption">{t("pairing.workspaces.caption")}</div>
      <div className="value">
        {expose.workspaces.map((workspace) => (
          <div key={workspace.id}>
            {/* L'identifiant dans son PROPRE élément : collé au dépôt, il n'est plus
                lisible seul — ni par un lecteur, ni par un test qui le cherche. */}
            <div className="row-title">{workspace.id}</div>
            {/* Le dépôt sous le workspace : c'est le couple qui dit d'où vient le
                paramétrage, et séparer les deux obligerait à les rapprocher de mémoire. */}
            <div className="row-sub">
              {workspace.repo_url ?? t("pairing.workspaces.noRepo")}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
