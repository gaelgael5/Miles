import type { Workspace } from "../api/workspaces";
import { type WorkspaceSelection, baseBranchOf } from "../layout/WorkspacesNav";
import { BranchScreen } from "./BranchScreen";
import { ChainScreen } from "./ChainScreen";
import { ChainsScreen } from "./ChainsScreen";
import { ContractScreen } from "./ContractScreen";
import { ContractsScreen } from "./ContractsScreen";
import { DataModelsScreen } from "./DataModelsScreen";
import { SourceScreen } from "./SourceScreen";
import { SourcesScreen } from "./SourcesScreen";

/** Écran d'une vue de branche ; null pour le paramétrage du workspace. */
export function branchScreen(
  workspace: Workspace,
  selection: NonNullable<WorkspaceSelection>,
  onSelect: (selection: WorkspaceSelection) => void,
) {
  const branch = selection.branch ?? baseBranchOf(workspace);
  if (selection.view === "settings" || branch === null) {
    return null;
  }
  const target = { workspaceId: workspace.id, branch };
  const back = () => onSelect(null);
  // La clé suit la branche : changer de branche repart d'un écran neuf, sans état d'une
  // autre branche (formulaire ouvert, aperçu) recopié par erreur.
  const key = `${branch}/${selection.view}/${selection.contract ?? ""}/${selection.chain ?? ""}/${selection.source ?? ""}`;
  if (selection.view === "contracts" && selection.contract !== undefined) {
    return (
      <ContractScreen
        key={key}
        target={target}
        slug={selection.contract}
        onBack={() => onSelect({ id: workspace.id, view: "contracts", branch })}
      />
    );
  }
  if (selection.view === "contracts") {
    return (
      <ContractsScreen
        key={key}
        workspace={workspace}
        target={target}
        onBack={back}
        onOpen={(contract) => onSelect({ id: workspace.id, view: "contracts", branch, contract })}
      />
    );
  }
  if (selection.view === "transformations" && selection.chain !== undefined) {
    return (
      <ChainScreen
        key={key}
        target={target}
        slug={selection.chain}
        onBack={() => onSelect({ id: workspace.id, view: "transformations", branch })}
      />
    );
  }
  if (selection.view === "transformations") {
    return (
      <ChainsScreen
        key={key}
        workspace={workspace}
        target={target}
        onBack={back}
        onOpen={(chain) => onSelect({ id: workspace.id, view: "transformations", branch, chain })}
      />
    );
  }
  if (selection.view === "sources" && selection.source !== undefined) {
    return (
      <SourceScreen
        key={key}
        target={target}
        name={selection.source}
        onBack={() => onSelect({ id: workspace.id, view: "sources", branch })}
      />
    );
  }
  if (selection.view === "sources") {
    return (
      <SourcesScreen
        key={key}
        workspace={workspace}
        target={target}
        onBack={back}
        onOpen={(source) => onSelect({ id: workspace.id, view: "sources", branch, source })}
      />
    );
  }
  if (selection.view === "dataModels") {
    return <DataModelsScreen key={key} workspace={workspace} target={target} onBack={back} />;
  }
  return <BranchScreen key={key} workspace={workspace} target={target} onBack={back} />;
}
