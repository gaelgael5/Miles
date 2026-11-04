import type { ReactElement } from "react";

import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";
import type { WorkspaceSelection } from "../layout/WorkspacesNav";
import { TradsCoverageScreen } from "./TradsCoverageScreen";
import { TradsKeysScreen } from "./TradsKeysScreen";
import { TradsScreen } from "./TradsScreen";

/**
 * Les écrans du référentiel de traductions, et l'aller-retour entre eux.
 *
 * Ils forment un trajet : on lit la couverture, on y clique sur ce qui manque, et on
 * arrive sur la saisie du bon contexte déjà filtrée sur la bonne culture. Rendu `null`
 * quand la sélection ne les concerne pas, pour que le routeur continue sa chaîne.
 */
export function tradsViewScreen({
  workspace,
  selection,
  target,
  onSelect,
  back,
  viewKey,
}: {
  workspace: Workspace;
  selection: NonNullable<WorkspaceSelection>;
  target: WorkTarget;
  onSelect: (selection: WorkspaceSelection) => void;
  back: () => void;
  viewKey: string;
}): ReactElement | null {
  const branch = target.branch;
  if (selection.view === "trads" && selection.tradsContext !== undefined) {
    return (
      <TradsKeysScreen
        // La culture du filtre entre dans la clé : revenir sur le même contexte par un
        // autre « N à traduire » doit repartir d'un écran filtré sur l'autre culture, et
        // non garder le filtre précédent (l'état initial ne se relit qu'au montage).
        key={`${viewKey}/${selection.tradsUntranslated ?? ""}`}
        target={target}
        context={selection.tradsContext}
        initialUntranslated={selection.tradsUntranslated}
        onBack={() => onSelect({ id: workspace.id, view: "trads", branch })}
      />
    );
  }
  if (selection.view === "trads") {
    return (
      <TradsScreen
        key={viewKey}
        target={target}
        onBack={back}
        onOpen={(tradsContext) =>
          onSelect({ id: workspace.id, view: "trads", branch, tradsContext })
        }
      />
    );
  }
  if (selection.view === "tradsCoverage") {
    return (
      <TradsCoverageScreen
        key={viewKey}
        target={target}
        onBack={back}
        onOpen={(tradsContext, tradsUntranslated) =>
          onSelect({
            id: workspace.id,
            view: "trads",
            branch,
            tradsContext,
            tradsUntranslated,
          })
        }
      />
    );
  }
  return null;
}
