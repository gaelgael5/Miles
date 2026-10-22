import { useContracts } from "../api/contracts";
import type { WorkTarget } from "../api/workTarget";

/**
 * Contrats déclarés dans une branche, sous « Contrats » (Gael, 22/10/2026) : on déclare
 * le contrat, il apparaît ici, et on l'ouvre pour y intégrer les fichiers du tiers. Lus
 * seulement quand la branche est dépliée : chaque lecture clone la branche.
 */
export function ContractLinks({
  target,
  open,
  current,
  onSelect,
}: {
  target: WorkTarget;
  open: boolean;
  current: string | undefined;
  onSelect: (contract: string) => void;
}) {
  const contracts = useContracts(target, open);
  return (
    <>
      {contracts.data?.map((contract) => (
        <button
          key={contract.slug}
          type="button"
          className="sidebar-link sidebar-contractlink"
          aria-current={current === contract.slug ? "page" : undefined}
          onClick={() => onSelect(contract.slug)}
        >
          {contract.label}
        </button>
      ))}
    </>
  );
}
