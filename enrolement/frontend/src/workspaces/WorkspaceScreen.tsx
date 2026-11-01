import { useTranslation } from "react-i18next";

import { PageHead } from "@miles/socle-web";

import { useExposedWorkspaces } from "../api/confiedGit";
import type { Environment } from "../api/environments";

/**
 * Un workspace hébergé par un environnement : d'où il vient, et la version qu'il sert.
 *
 * L'écran existe dès qu'un workspace est placé (Gael, 01/11/2026). Ce qu'il peut montrer
 * aujourd'hui s'arrête à ce que ce module SAIT : l'environnement qui l'héberge et le
 * dépôt que le module de paramétrage nous a confié. La version, elle, n'est connue de
 * personne ici — aucune route de pair ne la demande au module de paramétrage —, et c'est
 * dit plutôt que remplacé par une liste vide, qui se lirait comme un paramétrage sans
 * version publiée.
 */
export function WorkspaceScreen({ environnement }: { environnement: Environment }) {
  const { t } = useTranslation();
  const expose = useExposedWorkspaces();
  const workspace = environnement.workspace_id;
  const depot = expose.workspaces.find((w) => w.id === workspace)?.repo_url ?? null;

  return (
    <section className="section" aria-labelledby="workspace-title">
      <PageHead
        id="workspace-title"
        title={t("workspaces.title", { workspace })}
        lead={t("workspaces.lead", {
          label: environnement.label,
          slug: environnement.slug,
        })}
      />
      <div className="card">
        <div className="card-head">
          <h2>{t("workspaces.source.title")}</h2>
        </div>
        <dl className="facts">
          <div>
            <dt className="caption">{t("workspaces.source.captionEnvironment")}</dt>
            <dd className="value">
              {environnement.label} <span className="muted">{environnement.slug}</span>
            </dd>
          </div>
          <div>
            <dt className="caption">{t("workspaces.source.captionRepo")}</dt>
            <dd className="value">
              {depot ?? <span className="muted">{t("workspaces.source.noRepo")}</span>}
            </dd>
          </div>
        </dl>
      </div>
      <div className="card">
        <div className="card-head">
          <h2>{t("workspaces.version.title")}</h2>
        </div>
        {/* Une liste vide se lirait « ce workspace n'a aucune version publiée », ce qui
            serait une affirmation sur l'état du paramétrage — que ce module ne connaît
            pas. On dit donc ce qui manque, et où il manque. */}
        <p className="alert" role="status">
          {t("workspaces.version.unavailable")}
        </p>
      </div>
    </section>
  );
}
