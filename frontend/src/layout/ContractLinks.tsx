import { useContracts } from "../api/contracts";
import type { WorkspaceSelection } from "./WorkspacesNav";

/**
 * Contrats déclarés, sous « Contrats » du workspace (Gael, 22/10/2026) : on déclare le
 * contrat, il apparaît ici, et on l'ouvre pour y intégrer les fichiers du tiers. Lus
 * seulement quand le workspace est déplié : chaque lecture clone la branche de travail.
 */
export function ContractLinks({
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
  const contracts = useContracts(workspaceId, open);
  return (
    <>
      {contracts.data?.map((contract) => (
        <button
          key={contract.slug}
          type="button"
          className="sidebar-link sidebar-subsublink"
          aria-current={
            active && selection?.id === workspaceId && selection.contract === contract.slug
              ? "page"
              : undefined
          }
          onClick={() => onSelect({ id: workspaceId, view: "contracts", contract: contract.slug })}
        >
          {contract.label}
        </button>
      ))}
    </>
  );
}
