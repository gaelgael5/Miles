import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";

import { useBranches } from "../api/branches";
import { ContractLinks } from "./ContractLinks";
import type { WorkspaceSelection } from "./WorkspacesNav";

const BRANCH_VIEWS = ["dataModels", "contracts"] as const;

/**
 * Branches de travail d'un workspace, par leur slug (Gael, 22/10/2026). Lues seulement
 * quand le workspace est déplié. Le nom ouvre la branche (ses versions) et la déplie sur
 * ses vues : chacune lit et écrit dans cette branche-là.
 */
export function BranchLinks({
  workspaceId,
  open,
  active,
  selection,
  onSelect,
}: {
  workspaceId: string;
  open: boolean;
  active: boolean;
  selection: WorkspaceSelection;
  onSelect: (selection: WorkspaceSelection) => void;
}) {
  const { t } = useTranslation();
  const branches = useBranches(workspaceId, open);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const here = active && selection?.id === workspaceId ? selection : null;

  function openBranch(slug: string) {
    setExpanded((current) => new Set(current).add(slug));
    onSelect({ id: workspaceId, view: "branch", branch: slug });
  }

  return (
    <>
      {branches.data?.map((branch) => {
        const unfolded = expanded.has(branch.slug) || here?.branch === branch.slug;
        const listId = `sidebar-branch-${workspaceId}-${branch.slug}`;
        const target = { workspaceId, branch: branch.slug };
        return (
          <div key={branch.slug}>
            <button
              type="button"
              className="sidebar-link sidebar-sublink sidebar-branch"
              aria-expanded={unfolded}
              aria-controls={listId}
              aria-current={
                here?.branch === branch.slug && here.view === "branch" ? "page" : undefined
              }
              title={branch.label}
              onClick={() => openBranch(branch.slug)}
            >
              {branch.slug}
            </button>
            <div id={listId} hidden={!unfolded}>
              {BRANCH_VIEWS.map((view) => (
                <Fragment key={view}>
                  <button
                    type="button"
                    className="sidebar-link sidebar-subsublink"
                    aria-current={
                      here?.branch === branch.slug &&
                      here.view === view &&
                      here.contract === undefined
                        ? "page"
                        : undefined
                    }
                    onClick={() => onSelect({ id: workspaceId, view, branch: branch.slug })}
                  >
                    {t(`workspaces.card.${view}`)}
                  </button>
                  {view === "contracts" && (
                    <ContractLinks
                      target={target}
                      open={unfolded}
                      current={here?.branch === branch.slug ? here.contract : undefined}
                      onSelect={(contract) =>
                        onSelect({ id: workspaceId, view, branch: branch.slug, contract })
                      }
                    />
                  )}
                </Fragment>
              ))}
            </div>
          </div>
        );
      })}
    </>
  );
}
