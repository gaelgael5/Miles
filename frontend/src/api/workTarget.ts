/**
 * Où travaille l'atelier : un workspace et l'une de ses branches de travail, désignée par
 * son slug (story 6a74c474). Chaque branche a ses propres modèles, contrats et versions :
 * la branche fait partie de chaque adresse et de chaque clé de cache.
 */
export interface WorkTarget {
  workspaceId: string;
  branch: string;
  /**
   * La racine du workspace est en lecture seule (Gael, 22/10/2026, story dca0eb0e) : on
   * modifie dans une branche enfant. L'écran n'en offre pas les boutons ; le serveur, lui,
   * refuse de toute façon (`branche_racine_lecture_seule`).
   */
  readOnly: boolean;
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
