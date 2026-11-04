/** Un commit tel que le serveur le rend (route `/branches/graph`). */
export interface Commit {
  sha: string;
  /** Vide : le commit est à la frontière de ce qui a été lu, sa voie s'arrête là. */
  parents: string[];
  author: string;
  written_at: string;
  subject: string;
  refs: string[];
}

/** Un commit placé : sa ligne, sa voie, et les traits qui descendent vers ses parents. */
export interface PlacedCommit {
  commit: Commit;
  row: number;
  lane: number;
  edges: Edge[];
}

/** Un trait du commit vers un parent. `toRow` absent : le parent n'a pas été lu. */
export interface Edge {
  fromLane: number;
  toLane: number;
  toRow: number | null;
}

export interface Lanes {
  placed: PlacedCommit[];
  /** Nombre de voies occupées : la largeur à dessiner. */
  width: number;
}

/**
 * Place les commits en voies, façon graphe git (Gael, 24/10/2026).
 *
 * Principe, celui de tous les dessins d'historique : chaque voie ATTEND un sha. Un commit
 * prend la voie qui l'attendait — c'est ainsi qu'un enfant et son parent restent alignés
 * — puis cède la place à son premier parent. Ses autres parents ouvrent de nouvelles
 * voies, et c'est ce qui dessine une fusion.
 *
 * Les commits arrivent du plus récent au plus ancien : un parent est donc toujours PLUS
 * BAS dans la liste, et un trait descend toujours.
 */
export function layout(commits: Commit[]): Lanes {
  const rowOf = new Map(commits.map((c, index) => [c.sha, index]));
  // Ce que chaque voie attend ; `null` = voie libre, réutilisable.
  const waiting: (string | null)[] = [];
  let width = 0;

  function take(sha: string): number {
    const held = waiting.indexOf(sha);
    if (held !== -1) {
      return held;
    }
    const free = waiting.indexOf(null);
    if (free !== -1) {
      waiting[free] = sha;
      return free;
    }
    waiting.push(sha);
    return waiting.length - 1;
  }

  const placed = commits.map((commit, row) => {
    const lane = take(commit.sha);
    // La voie du commit passe à son PREMIER parent : la branche continue tout droit.
    waiting[lane] = commit.parents[0] ?? null;
    const edges: Edge[] = commit.parents.map((parent, rank) => {
      // Le premier parent reste sur place ; les suivants s'ouvrent une voie à eux.
      const toLane = rank === 0 ? lane : take(parent);
      return { fromLane: lane, toLane, toRow: rowOf.get(parent) ?? null };
    });
    width = Math.max(width, waiting.filter((w) => w !== null).length, lane + 1);
    return { commit, row, lane, edges };
  });

  return { placed, width: Math.max(width, 1) };
}
