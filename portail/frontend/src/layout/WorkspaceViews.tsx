import { Fragment } from "react";
import { useTranslation } from "react-i18next";

import { CollapsibleGroup } from "@miles/socle-web";

import type { Direction } from "../api/contracts";
import { DEVICE_SENSES } from "../api/dataModels";
import { ContractLinks } from "./ContractLinks";
import { EventPerimeterLinks } from "./EventPerimeterLinks";
import type { WorkspaceSelection, WorkspaceView } from "./WorkspacesNav";

// « branch » en tête : c'est l'écran de la branche qu'on regarde — ses versions et le
// graphe de toutes les branches du workspace, fondus le 01/11/2026 (Gael). Il situe où
// l'on travaille avant d'ouvrir quoi que ce soit.
const VIEWS: WorkspaceView[] = [
  "branch",
  "dataModels",
  // Les événements juste après les modèles (Gael, 11/11/2026) : ils se construisent
  // avec le même écran, et l'un peut décrire son payload avec l'autre. Leur liste,
  // elle, reste séparée — c'est tout l'objet de la décision.
  "events",
  "contracts",
  "transformations",
  // Les workflows après les transformations et avant les storages : un workflow réagit
  // aux types d'event déclarés plus haut, et son comportement se lit avant de savoir où
  // les objets sont rangés. Il INCLUT des périmètres, donc il ne peut pas vivre sous
  // l'un d'eux — c'est aussi pourquoi son fichier est à la racine de la branche
  // (`miles.workflows.layout`).
  "workflows",
  // « storages » avant « sources » : on déclare ce qui est stocké avant de dire
  // comment on le remplit (Gael, 24/10/2026 — deux notions distinctes).
  "storages",
  // La référence de compte juste après les storages : elle en DÉSIGNE un, et on ne peut
  // pas la régler avant d'en avoir déclaré (story a3ece1e9).
  "accountReference",
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
          {view === "dataModels" ||
          view === "contracts" ||
          view === "trads" ||
          view === "events" ? (
            <CollapsibleGroup
              className="sidebar-link sidebar-sublink sidebar-group-link"
              label={t(`workspaces.card.${view}`)}
            >
              <button
                type="button"
                className="sidebar-link sidebar-subsublink"
                aria-current={
                  here && selection?.view === view && selection.contract === undefined &&
                  selection.model === undefined && selection.scope === undefined &&
                  selection.device === undefined
                    ? "page"
                    : undefined
                }
                onClick={() => onSelect({ id: workspaceId, view, branch })}
              >
                {t(`workspaces.nav.all_${view}`)}
              </button>
              {view === "events" ? (
                // Un sous-menu par PÉRIMÈTRE (Gael, 12/11/2026) : son clic lit l'artefact
                // du périmètre et affiche son référentiel.
                <EventPerimeterLinks
                  // Des liens qui ne font que lire : aucun geste d'écriture ne part du menu.
                  target={{
                    workspaceId,
                    branch,
                    readOnly: true,
                    canFreeze: false,
                    canMigrate: false,
                  }}
                  open={open}
                  current={here ? selection?.scope : undefined}
                  onSelect={(scope) => onSelect({ id: workspaceId, view, branch, scope })}
                />
              ) : view === "trads" ? (
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
                <>
                  {/* Modèles dérivés des contrats, par sens (story 47f55d8b). */}
                  {SENSES.map((sens) => (
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
                  ))}
                  {/* Les messages du tuyau terminal, par sens (story 31025fe6). Sous
                      « Modèles de données » parce que c'en SONT, déclarés à la main comme
                      les pivots — et non sous « Événements », où rien ne les déclare. */}
                  {DEVICE_SENSES.map((sens) => (
                    <button
                      key={sens}
                      type="button"
                      className="sidebar-link sidebar-subsublink"
                      aria-current={
                        here && selection?.view === "dataModels" && selection.device === sens &&
                        selection.model === undefined
                          ? "page"
                          : undefined
                      }
                      onClick={() =>
                        onSelect({ id: workspaceId, view: "dataModels", branch, device: sens })
                      }
                    >
                      {t(`dataModels.devices.${sens}`)}
                    </button>
                  ))}
                </>
              ) : (
                <ContractLinks
                  // Des liens qui ne font que lire : aucun geste d'écriture ne part du menu.
                  target={{ workspaceId, branch, readOnly: true, canFreeze: false, canMigrate: false }}
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
