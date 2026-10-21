import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type Workspace, useWorkspaces } from "../api/workspaces";

export type WorkspaceView = "settings" | "dataModels" | "contracts";
/** Ce qu'affiche l'écran Workspaces : la liste (null), ou une vue d'un workspace. */
export type WorkspaceSelection = { id: string; view: WorkspaceView } | null;

/** Vues d'un workspace, dans l'ordre du sous-menu. */
export function viewsOf(workspace: Workspace): WorkspaceView[] {
  // Modèles et contrats s'écrivent dans la branche de travail : sans elle, rien à ouvrir.
  return workspace.work_branch === null ? ["settings"] : ["dataModels", "contracts", "settings"];
}

/**
 * Sous-menu des workspaces (Gael, 21/10/2026) : la liste, puis chaque workspace, dont
 * le sous-sous-menu ouvre ses vues. Un workspace est replié par défaut, sauf celui
 * qu'on regarde : avec beaucoup de workspaces, tout déplier noierait le menu.
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
        return (
          <div key={workspace.id}>
            <button
              type="button"
              className="sidebar-link sidebar-workspace"
              aria-expanded={open}
              aria-controls={listId}
              onClick={() => toggle(workspace.id)}
            >
              {workspace.name}
            </button>
            <div id={listId} hidden={!open}>
              {viewsOf(workspace).map((view) => (
                <button
                  key={view}
                  type="button"
                  className="sidebar-link sidebar-sublink"
                  aria-current={
                    active && selection?.id === workspace.id && selection.view === view
                      ? "page"
                      : undefined
                  }
                  onClick={() => onSelect({ id: workspace.id, view })}
                >
                  {t(`workspaces.card.${view}`)}
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </>
  );
}
