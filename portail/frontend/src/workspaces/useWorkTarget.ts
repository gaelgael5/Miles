import { useHolds } from "../api/holds";
import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";
import { baseBranchOf } from "../layout/WorkspacesNav";

/**
 * Ce que la personne peut faire sur la branche regardée. Tant que les prises de main ne
 * sont pas lues, rien ne s'offre : mieux vaut un bouton absent un instant qu'un bouton
 * que le serveur refusera.
 */
export function useWorkTarget(workspace: Workspace, branch: string): WorkTarget {
  const root = branch === baseBranchOf(workspace);
  const holds = useHolds(workspace.id, !root);
  const mine = holds.data?.some((h) => h.slug === branch && h.mine) ?? false;
  return { workspaceId: workspace.id, branch, readOnly: root || !mine, canFreeze: root || mine };
}
