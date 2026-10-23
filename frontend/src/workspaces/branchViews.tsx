import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";
import { HoldNotice } from "./HoldNotice";
import { RootReadOnlyNotice } from "./RootReadOnlyNotice";
import { useWorkTarget } from "./useWorkTarget";
import { type WorkspaceSelection, baseBranchOf } from "../layout/WorkspacesNav";
import { BranchScreen } from "./BranchScreen";
import { ChainScreen } from "./ChainScreen";
import { ChainsScreen } from "./ChainsScreen";
import { ContractModelsScreen } from "./ContractModelsScreen";
import { ContractScreen } from "./ContractScreen";
import { ContractsScreen } from "./ContractsScreen";
import { DataModelScreen } from "./DataModelScreen";
import { DataModelsScreen } from "./DataModelsScreen";
import { DerivedModelScreen } from "./DerivedModelScreen";
import { SourceScreen } from "./SourceScreen";
import { SourcesScreen } from "./SourcesScreen";

/** Une vue de branche s'affiche-t-elle ? Non pour le paramétrage, ni sans branche de base. */
export function hasBranchScreen(workspace: Workspace, selection: NonNullable<WorkspaceSelection>) {
  return selection.view !== "settings" && (selection.branch ?? baseBranchOf(workspace)) !== null;
}

/**
 * Écran d'une vue de branche, avec ce qui dit pourquoi rien ne s'y modifie : la racine
 * en lecture seule, ou une branche enfant dont on n'a pas la main (9def0adc).
 */
export function BranchViewScreen({
  workspace,
  selection,
  onSelect,
}: {
  workspace: Workspace;
  selection: NonNullable<WorkspaceSelection>;
  onSelect: (selection: WorkspaceSelection) => void;
}) {
  const branch = selection.branch ?? baseBranchOf(workspace) ?? "";
  const target = useWorkTarget(workspace, branch);
  const root = branch === baseBranchOf(workspace);
  return (
    <>
      {root && <RootReadOnlyNotice />}
      {!root && target.readOnly && <HoldNotice workspaceId={workspace.id} branch={branch} />}
      {viewScreen(workspace, selection, target, onSelect)}
    </>
  );
}

function viewScreen(
  workspace: Workspace,
  selection: NonNullable<WorkspaceSelection>,
  target: WorkTarget,
  onSelect: (selection: WorkspaceSelection) => void,
) {
  const branch = target.branch;
  const back = () => onSelect(null);
  // La clé suit la branche : changer de branche repart d'un écran neuf, sans état d'une
  // autre branche (formulaire ouvert, aperçu) recopié par erreur.
  const key = `${branch}/${selection.view}/${selection.contract ?? ""}/${selection.chain ?? ""}/${selection.source ?? ""}/${selection.model ?? ""}/${selection.sens ?? ""}/${selection.derived ?? ""}`;
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
  if (selection.view === "contractModels") {
    const sens = selection.sens ?? "entrant";
    const list = () => onSelect({ id: workspace.id, view: "contractModels", branch, sens });
    if (selection.derived !== undefined) {
      const [slug = "", version = "0", name = ""] = selection.derived.split("/");
      return (
        <DerivedModelScreen
          key={key}
          target={target}
          derived={{ slug, version: Number(version), name }}
          onBack={list}
        />
      );
    }
    return (
      <ContractModelsScreen
        key={key}
        workspace={workspace}
        target={target}
        sens={sens}
        onBack={back}
        onOpen={(ref) =>
          onSelect({
            id: workspace.id,
            view: "contractModels",
            branch,
            sens,
            derived: `${ref.slug}/${ref.version}/${ref.name}`,
          })
        }
      />
    );
  }
  if (selection.view === "dataModels" && selection.model !== undefined) {
    const [scope = "", name = ""] = selection.model.split("/");
    return (
      <DataModelScreen
        key={key}
        target={target}
        scope={scope}
        name={name}
        onBack={() => onSelect({ id: workspace.id, view: "dataModels", branch })}
      />
    );
  }
  if (selection.view === "dataModels") {
    return (
      <DataModelsScreen
        key={key}
        workspace={workspace}
        target={target}
        onBack={back}
        onOpen={(m) =>
          onSelect({ id: workspace.id, view: "dataModels", branch, model: `${m.scope}/${m.name}` })
        }
      />
    );
  }
  return <BranchScreen key={key} workspace={workspace} target={target} onBack={back} />;
}
