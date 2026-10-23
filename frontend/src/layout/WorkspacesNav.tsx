import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useBranchViews } from "../api/branches";
import type { Direction } from "../api/contracts";
import { type Workspace, useWorkspaces } from "../api/workspaces";
import { WorkspaceViews } from "./WorkspaceViews";

export type WorkspaceView =
  | "settings"
  | "branch"
  | "dataModels"
  | "contractModels"
  | "contracts"
  | "transformations"
  | "sources";
/**
 * Ce qu'affiche l'écran Workspaces : la liste (null), le paramétrage d'un workspace, ou
 * une vue d'une de ses branches de travail (`branch`, son slug) — l'un de ses contrats
 * compris (`contract`, avec la vue « contracts »).
 */
export type WorkspaceSelection = {
  id: string;
  view: WorkspaceView;
  branch?: string;
  contract?: string;
  // Une chaîne de transformations ouverte, avec la vue « transformations ».
  chain?: string;
  // Une source de données ouverte, avec la vue « sources ».
  source?: string;
  // Un modèle de données ouvert (« portée/nom »), avec la vue « dataModels ».
  model?: string;
  // Le sens des contrats dont on liste les modèles, avec la vue « contractModels ».
  sens?: Direction;
  // Un modèle dérivé ouvert (« contrat/version/nom »), avec la vue « contractModels ».
  derived?: string;
} | null;

/** Slug de la branche de base : celle qu'ouvrent les boutons de la liste des workspaces. */
export function baseBranchOf(workspace: Workspace): string | null {
  return workspace.work_branch?.replace(/^work\//, "") ?? null;
}

/** Branche que la personne regarde dans ce workspace : son choix, ou la base. */
export function viewedBranchOf(
  workspace: Workspace,
  views: Record<string, string> | undefined,
): string | null {
  return views?.[workspace.id] ?? baseBranchOf(workspace);
}

/** Vues offertes sur la ligne d'un workspace, dans « Tous les workspaces ». */
export function viewsOf(workspace: Workspace): WorkspaceView[] {
  // Modèles et contrats s'écrivent dans une branche de travail : sans elle, rien à ouvrir.
  return workspace.work_branch === null ? ["settings"] : ["dataModels", "contracts", "settings"];
}

/**
 * Sous-menu des workspaces : la liste, puis chaque workspace libellé « nom (branche) »
 * d'après la branche que la personne regarde (Gael, 22/10/2026), déplié sur les vues de
 * cette branche. Replié par défaut, sauf ce qu'on regarde : avec beaucoup de workspaces,
 * tout déplier noierait le menu.
 */
export function WorkspacesNav({
  active,
  selection,
  onSelect,
}: {
  active: boolean;
  selection: WorkspaceSelection;
  onSelect: (selection: WorkspaceSelection) => void;
}) {
  const { t } = useTranslation();
  const workspaces = useWorkspaces();
  const views = useBranchViews();
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  function toggle(id: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (!next.delete(id)) {
        next.add(id);
      }
      return next;
    });
  }

  return (
    <>
      <button
        type="button"
        className="sidebar-link"
        aria-current={active && selection === null ? "page" : undefined}
        onClick={() => onSelect(null)}
      >
        {t("app.nav.allWorkspaces")}
      </button>
      {workspaces.data?.map((workspace) => {
        const open = expanded.has(workspace.id) || selection?.id === workspace.id;
        const listId = `sidebar-workspace-${workspace.id}`;
        // Le paramétrage du workspace se fait depuis « Tous les workspaces » et n'est pas
        // répété dans le menu (Gael, 22/10/2026). Sans branche de travail, il n'y a rien
        // à déplier : le nom ouvre alors directement ce paramétrage.
        if (workspace.work_branch === null) {
          return (
            <button
              key={workspace.id}
              type="button"
              className="sidebar-link"
              aria-current={active && selection?.id === workspace.id ? "page" : undefined}
              onClick={() => onSelect({ id: workspace.id, view: "settings" })}
            >
              {workspace.name}
            </button>
          );
        }
        const branch = viewedBranchOf(workspace, views.data) ?? "";
        return (
          <div key={workspace.id}>
            <button
              type="button"
              className="sidebar-link sidebar-workspace"
              aria-expanded={open}
              aria-controls={listId}
              onClick={() => toggle(workspace.id)}
            >
              {t("app.nav.workspaceOnBranch", { name: workspace.name, branch })}
            </button>
            <div id={listId} hidden={!open}>
              <WorkspaceViews
                workspaceId={workspace.id}
                branch={branch}
                open={open}
                active={active}
                selection={selection}
                onSelect={onSelect}
              />
            </div>
          </div>
        );
      })}
    </>
  );
}
