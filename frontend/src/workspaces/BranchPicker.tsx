import { useTranslation } from "react-i18next";

import { useBranchViews, useBranches, useSetBranchView } from "../api/branches";
import type { Workspace } from "../api/workspaces";
import { viewedBranchOf } from "../layout/WorkspacesNav";

/**
 * Branche que la personne regarde dans ce workspace (Gael, 22/10/2026). Le choix est
 * retenu côté serveur pour son compte, et renomme le workspace dans son menu.
 */
export function BranchPicker({ workspace }: { workspace: Workspace }) {
  const { t } = useTranslation();
  const branches = useBranches(workspace.id);
  const views = useBranchViews();
  const choose = useSetBranchView(workspace.id);
  const current = viewedBranchOf(workspace, views.data) ?? "";
  const id = `branch-picker-${workspace.id}`;

  return (
    <div className="cell">
      <label className="caption" htmlFor={id}>
        {t("branches.viewed")}
      </label>
      <div className="value">
        <select
          id={id}
          value={current}
          disabled={!branches.isSuccess || choose.isPending}
          onChange={(e) => choose.mutate(e.target.value)}
        >
          {branches.data?.map((b) => (
            <option key={b.slug} value={b.slug}>
              {b.slug}
            </option>
          ))}
        </select>
        {choose.isError && (
          <p className="alert" role="alert">
            {t("branches.errors.view")}
          </p>
        )}
      </div>
    </div>
  );
}
