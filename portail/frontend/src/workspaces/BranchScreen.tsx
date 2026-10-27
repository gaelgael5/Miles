import { useTranslation } from "react-i18next";

import { useBranches } from "../api/branches";
import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";
import { VersionsPanel } from "./VersionsPanel";

/**
 * Une branche de travail : ce qu'on y fait (modèles, contrats…) lui est propre, et c'est
 * ici qu'on la fige en version (Gael, 22/10/2026). Le bouton n'est donc plus sur l'écran
 * des modèles : une version fige toute la branche, pas une seule de ses vues.
 */
export function BranchScreen({
  workspace,
  target,
  onBack,
}: {
  workspace: Workspace;
  target: WorkTarget;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const branches = useBranches(workspace.id);
  const branch = branches.data?.find((b) => b.slug === target.branch);

  return (
    <section aria-labelledby="branch-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="branch-title">
            {t("branches.title", { name: workspace.name, branch: target.branch })}
          </h1>
          {branch && (
            <p className="lead">
              {branch.label} · <span className="mono">{branch.branch}</span>{" "}
              {branch.base && <span className="badge badge-accent">{t("branches.base")}</span>}
            </p>
          )}
        </div>
      </div>
      <VersionsPanel target={target} />
    </section>
  );
}
