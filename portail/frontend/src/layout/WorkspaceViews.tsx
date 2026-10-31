import { Fragment } from "react";
import { useTranslation } from "react-i18next";

import type { Direction } from "../api/contracts";
import { CollapsibleGroup } from "./CollapsibleGroup";
import { ContractLinks } from "./ContractLinks";
import type { WorkspaceSelection, WorkspaceView } from "./WorkspacesNav";

// « branchGraph » en tête : c'est la vue d'ensemble des branches, celle qui situe où
// l'on travaille avant d'ouvrir quoi que ce soit.
const VIEWS: WorkspaceView[] = [
  "branchGraph",
  "branch",
  "dataModels",
  "contracts",
  "transformations",
  // « storages » avant « sources » : on déclare ce qui est stocké avant de dire
  // comment on le remplit (Gael, 24/10/2026 — deux notions distinctes).
  "storages",
  "sources",
  // Le référentiel de traductions (story 623898d1) : en dernier, c'est un magasin de
  // libellés, pas une étape du pipeline de données.
  "trads",
];
const SENSES: Direction[] = ["interne", "externe"];

/**
 * Vues de la branche que la personne regarde (Gael, 22/10/2026) : le menu ne liste pas
 * les branches, il montre celle qu'on a choisie dans « Tous les workspaces ».
 */
export function WorkspaceViews({
  workspaceId,
  branch,
  open,
  active,
  selection,
  onSelect,
}: {
  workspaceId: string;
  branch: string;
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
          {/* Une vue qui PORTE des entrées est repliable ; une vue seule reste un lien.
              Un bouton de repli sur une entrée sans enfant promettrait un niveau qui
              n'existe pas (Gael, 30/10/2026). */}
          {view === "dataModels" || view === "contracts" || view === "trads" ? (
            <CollapsibleGroup
              className="sidebar-link sidebar-sublink sidebar-group-link"
              label={t(`workspaces.card.${view}`)}
            >
              <button
                type="button"
                className="sidebar-link sidebar-subsublink"
                aria-current={
                  here && selection?.view === view && selection.contract === undefined &&
                  selection.model === undefined
                    ? "page"
                    : undefined
                }
                onClick={() => onSelect({ id: workspaceId, view, branch })}
              >
                {t(`workspaces.nav.all_${view}`)}
              </button>
              {view === "trads" ? (
                // La COUVERTURE à côté des contextes (story 82e60880) : lire ce qui
                // manque et gérer les contextes sont deux gestes, pas deux onglets d'un
                // même écran — celui qui traduit ne crée pas de répertoire.
                <button
                  type="button"
                  className="sidebar-link sidebar-subsublink"
                  aria-current={
                    here && selection?.view === "tradsCoverage" ? "page" : undefined
                  }
                  onClick={() =>
                    onSelect({ id: workspaceId, view: "tradsCoverage", branch })
                  }
                >
                  {t("workspaces.card.tradsCoverage")}
                </button>
              ) : view === "dataModels" ? (
                // Modèles dérivés des contrats, par sens (story 47f55d8b).
                SENSES.map((sens) => (
                  <button
                    key={sens}
                    type="button"
                    className="sidebar-link sidebar-subsublink"
                    aria-current={
                      here && selection?.view === "contractModels" && selection.sens === sens &&
                      selection.contract === undefined
                        ? "page"
                        : undefined
                    }
                    onClick={() =>
                      onSelect({ id: workspaceId, view: "contractModels", branch, sens })
                    }
                  >
                    {t(`contractModels.nav.${sens}`)}
                  </button>
                ))
              ) : (
                <ContractLinks
                  // Des liens qui ne font que lire : aucun geste d'écriture ne part du menu.
                  target={{ workspaceId, branch, readOnly: true, canFreeze: false }}
                  open={open}
                  current={here ? selection?.contract : undefined}
                  onSelect={(contract) => onSelect({ id: workspaceId, view, branch, contract })}
                />
              )}
            </CollapsibleGroup>
          ) : (
            <button
              type="button"
              className="sidebar-link sidebar-sublink"
              aria-current={
                here && selection?.view === view && selection.contract === undefined &&
                selection.chain === undefined &&
                selection.source === undefined &&
                selection.model === undefined
                  ? "page"
                  : undefined
              }
              onClick={() => onSelect({ id: workspaceId, view, branch })}
            >
              {t(`workspaces.card.${view}`)}
            </button>
          )}
        </Fragment>
      ))}
    </>
  );
}
