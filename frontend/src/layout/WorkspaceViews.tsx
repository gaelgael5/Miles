import { Fragment } from "react";
import { useTranslation } from "react-i18next";

import { ContractLinks } from "./ContractLinks";
import type { WorkspaceSelection, WorkspaceView } from "./WorkspacesNav";

const VIEWS: WorkspaceView[] = ["branch", "dataModels", "contracts", "transformations", "sources"];

/**
 * Vues de la branche que la personne regarde (Gael, 22/10/2026) : le menu ne liste pas
 * les branches, il montre celle qu'on a choisie dans « Tous les workspaces ».
 */
export function WorkspaceViews({
  workspaceId,
  branch,
  readOnly,
  open,
  active,
  selection,
  onSelect,
}: {
  workspaceId: string;
  branch: string;
  readOnly: boolean;
  open: boolean;
  active: boolean;
  selection: WorkspaceSelection;
  onSelect: (selection: WorkspaceSelection) => void;
}) {
  const { t } = useTranslation();
  const here = active && selection?.id === workspaceId && selection.branch === branch;
  return (
    <>
      {VIEWS.map((view) => (
        <Fragment key={view}>
          <button
            type="button"
            className="sidebar-link sidebar-sublink"
            aria-current={
              here && selection?.view === view && selection.contract === undefined &&
              selection.chain === undefined &&
              selection.source === undefined
                ? "page"
                : undefined
            }
            onClick={() => onSelect({ id: workspaceId, view, branch })}
          >
            {t(`workspaces.card.${view}`)}
          </button>
          {view === "contracts" && (
            <ContractLinks
              target={{ workspaceId, branch, readOnly }}
              open={open}
              current={here ? selection?.contract : undefined}
              onSelect={(contract) => onSelect({ id: workspaceId, view, branch, contract })}
            />
          )}
        </Fragment>
      ))}
    </>
  );
}
