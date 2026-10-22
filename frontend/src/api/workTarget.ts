/**
 * Où travaille l'atelier : un workspace et l'une de ses branches de travail, désignée par
 * son slug (story 6a74c474). Chaque branche a ses propres modèles, contrats et versions :
 * la branche fait partie de chaque adresse et de chaque clé de cache.
 */
export interface WorkTarget {
  workspaceId: string;
  branch: string;
}

/** Adresse d'une ressource de l'atelier sur la branche visée. */
export function atBranch(target: WorkTarget, ...segments: string[]): string {
  const path = segments.map(encodeURIComponent).join("/");
  const workspace = encodeURIComponent(target.workspaceId);
  return `/api/workspaces/${workspace}/${path}?branch=${encodeURIComponent(target.branch)}`;
}

export function branchKey(kind: string, target: WorkTarget) {
  return [kind, target.workspaceId, target.branch] as const;
}
