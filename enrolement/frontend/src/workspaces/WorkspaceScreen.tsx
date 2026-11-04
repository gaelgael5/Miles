import { useTranslation } from "react-i18next";

import { PageHead } from "@miles/socle-web";

import { useExposedWorkspaces } from "../api/confiedGit";
import type { Environment } from "../api/environments";
import { HostedVersion } from "./HostedVersion";

/**
 * Un workspace hébergé par un environnement : d'où il vient, et la version qu'il sert.
 *
 * L'écran existe dès qu'un workspace est placé (Gael, 01/11/2026). Les versions sont
 * lisibles depuis le 01/11/2026 au soir (story 3bbd4f87) : ce module lit le dépôt
 * lui-même, avec le credential que le module de paramétrage lui confie. Aucune route de
 * pair ne les lui demande, et c'est le choix qui a été fait — en passer par le
 * paramétrage ferait dépendre toute lecture de git de sa disponibilité.
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
      <HostedVersion environmentId={environnement.id} />
    </section>
  );
}
