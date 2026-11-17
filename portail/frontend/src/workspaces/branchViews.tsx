import type { ModelUsage } from "../api/dataModels";
import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";
import { HoldNotice } from "./HoldNotice";
import { LayoutNotice } from "./LayoutNotice";
import { RootReadOnlyNotice } from "./RootReadOnlyNotice";
import { useWorkTarget } from "./useWorkTarget";
import { type WorkspaceSelection, baseBranchOf } from "../layout/WorkspacesNav";
import { AccountReferenceScreen } from "./AccountReferenceScreen";
import { BranchScreen } from "./BranchScreen";
import { ChainScreen } from "./ChainScreen";
import { ChainsScreen } from "./ChainsScreen";
import { ContractModelsScreen } from "./ContractModelsScreen";
import { SwaggerScreen } from "../contracts/SwaggerScreen";
import { ContractScreen } from "./ContractScreen";
import { ContractsScreen } from "./ContractsScreen";
import { DataModelScreen } from "./DataModelScreen";
import { DataModelsScreen } from "./DataModelsScreen";
import { EventsScreen } from "./EventsScreen";
import { DerivedModelScreen } from "./DerivedModelScreen";
import { SourceScreen } from "./SourceScreen";
import { SourcesScreen } from "./SourcesScreen";
import { StorageScreen } from "./StorageScreen";
import { StoragesScreen } from "./StoragesScreen";
import { WorkflowsScreen } from "./WorkflowsScreen";
import { tradsViewScreen } from "./tradsViews";

/**
 * Où va-t-on en ouvrant ce qui désigne un modèle (story e36192f8) ?
 *
 * Le lien est ICI et non dans l'écran du modèle : la correspondance entre une nature de
 * désignation et une vue de branche est la même affaire que les autres allers-retours de
 * ce fichier, et un écran qui construirait sa propre sélection en aurait fait une
 * deuxième source. Un type d'event mène à la LISTE des events : l'écran n'a pas de
 * sélection par type, et en inventer une ici promettrait une page qui n'existe pas.
 */
function usageSelection(
  id: string,
  branch: string,
  usage: ModelUsage,
): NonNullable<WorkspaceSelection> {
  if (usage.kind === "storage") {
    return { id, view: "storages", branch, storage: usage.name };
  }
  if (usage.kind === "source") {
    return { id, view: "sources", branch, source: usage.name };
  }
  if (usage.kind === "chain_step") {
    return {
      id,
      view: "transformations",
      branch,
      chain: usage.name,
      step: usage.part ?? undefined,
    };
  }
  if (usage.kind === "model") {
    // Le nom d'un modèle désignateur est déjà « portée/nom » : c'est la clef de sélection.
    return { id, view: "dataModels", branch, model: usage.name };
  }
  return { id, view: "events", branch };
}

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
      <LayoutNotice target={target} />
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
  const key = `${branch}/${selection.view}/${selection.contract ?? ""}/${selection.chain ?? ""}/${selection.step ?? ""}/${selection.source ?? ""}/${selection.storage ?? ""}/${selection.swagger ?? ""}/${selection.model ?? ""}/${selection.sens ?? ""}/${selection.derived ?? ""}/${selection.scope ?? ""}`;
  if (
    selection.view === "contracts" &&
    selection.contract !== undefined &&
    selection.swagger !== undefined
  ) {
    const version = Number(selection.swagger.replace("v", ""));
    return (
      <SwaggerScreen
        key={key}
        target={target}
        subject={{ kind: "contract", slug: selection.contract, version }}
        title={`${selection.contract} — v${version}`}
        onBack={() =>
          onSelect({
            id: workspace.id,
            view: "contracts",
            branch,
            contract: selection.contract,
          })
        }
      />
    );
  }
  if (selection.view === "sources" && selection.source !== undefined && selection.swagger) {
    return (
      <SwaggerScreen
        key={key}
        target={target}
        subject={{ kind: "source", name: selection.source }}
        title={selection.source}
        onBack={() =>
          onSelect({ id: workspace.id, view: "sources", branch, source: selection.source })
        }
      />
    );
  }
  if (selection.view === "contracts" && selection.contract !== undefined) {
    return (
      <ContractScreen
        key={key}
        target={target}
        slug={selection.contract}
        onBack={() => onSelect({ id: workspace.id, view: "contracts", branch })}
        onSwagger={(version) =>
          onSelect({
            id: workspace.id,
            view: "contracts",
            branch,
            contract: selection.contract,
            swagger: `v${version}`,
          })
        }
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
        step={selection.step}
        onOpenStep={(step) =>
          onSelect({
            id: workspace.id,
            view: "transformations",
            branch,
            chain: selection.chain,
            step: step ?? undefined,
          })
        }
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
  if (selection.view === "storages" && selection.storage !== undefined) {
    return (
      <StorageScreen
        key={key}
        target={target}
        name={selection.storage}
        onBack={() => onSelect({ id: workspace.id, view: "storages", branch })}
      />
    );
  }
  // Les trois écrans de traductions sont à part : ils partagent le même aller-retour
  // entre la couverture, les contextes et la saisie, et les garder ici faisait dépasser
  // ce fichier de la taille que le dépôt s'impose.
  const trads = tradsViewScreen({ workspace, selection, target, onSelect, back, viewKey: key });
  if (trads !== null) {
    return trads;
  }
  if (selection.view === "storages") {
    return (
      <StoragesScreen
        key={key}
        workspace={workspace}
        target={target}
        onBack={back}
        onOpen={(storage) => onSelect({ id: workspace.id, view: "storages", branch, storage })}
      />
    );
  }
  if (selection.view === "workflows") {
    return <WorkflowsScreen key={key} workspace={workspace} target={target} onBack={back} />;
  }
  if (selection.view === "accountReference") {
    return (
      <AccountReferenceScreen key={key} workspace={workspace} target={target} onBack={back} />
    );
  }
  if (selection.view === "sources" && selection.source !== undefined) {
    return (
      <SourceScreen
        key={key}
        target={target}
        name={selection.source}
        onBack={() => onSelect({ id: workspace.id, view: "sources", branch })}
        onSwagger={() =>
          onSelect({
            id: workspace.id,
            view: "sources",
            branch,
            source: selection.source,
            swagger: "api",
          })
        }
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
    const sens = selection.sens ?? "interne";
    const at = (contract?: string) =>
      onSelect({ id: workspace.id, view: "contractModels", branch, sens, contract });
    if (selection.derived !== undefined) {
      const [slug = "", version = "0", name = ""] = selection.derived.split("/");
      return (
        <DerivedModelScreen
          key={key}
          target={target}
          derived={{ slug, version: Number(version), name }}
          onBack={() => at(slug)}
        />
      );
    }
    return (
      <ContractModelsScreen
        key={key}
        workspace={workspace}
        target={target}
        sens={sens}
        contract={selection.contract}
        onBack={back}
        onContract={at}
        onOpen={(ref) =>
          onSelect({
            id: workspace.id,
            view: "contractModels",
            branch,
            sens,
            contract: ref.slug,
            derived: `${ref.slug}/${ref.version}/${ref.name}`,
          })
        }
      />
    );
  }
  if (selection.view === "events") {
    return (
      <EventsScreen
        key={key}
        workspace={workspace}
        target={target}
        scope={selection.scope}
        onBack={back}
        // Le payload d'un type d'event est un modèle ORDINAIRE : il s'édite par l'écran
        // des modèles, et non par un éditeur propre aux events qui n'existe plus.
        onOpenModel={(d) =>
          onSelect({
            id: workspace.id,
            view: "dataModels",
            branch,
            model: `${d.model_scope}/${d.model_name}`,
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
        onOpenUsage={(usage) => onSelect(usageSelection(workspace.id, branch, usage))}
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
