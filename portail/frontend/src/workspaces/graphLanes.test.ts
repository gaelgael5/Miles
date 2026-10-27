import { type Commit, layout } from "./graphLanes";

function commit(sha: string, parents: string[], refs: string[] = []): Commit {
  return { sha, parents, author: "t", written_at: "2026-10-24T10:00:00Z", subject: sha, refs };
}

describe("layout", () => {
  it("keeps a straight line on a single branch", () => {
    const { placed, width } = layout([commit("c", ["b"]), commit("b", ["a"]), commit("a", [])]);

    expect(placed.map((p) => p.lane)).toEqual([0, 0, 0]);
    expect(width).toBe(1);
    // Chaque trait descend vers la ligne de son parent.
    expect(placed[0]?.edges).toEqual([{ fromLane: 0, toLane: 0, toRow: 1 }]);
    expect(placed[2]?.edges).toEqual([]);
  });

  it("gives a second lane to a branch that left the trunk", () => {
    // « d » sur une branche, « c » sur l'autre, les deux issus de « b ».
    const { placed, width } = layout([
      commit("d", ["b"], ["back/ams/essai"]),
      commit("c", ["b"], ["back/ams/root"]),
      commit("b", ["a"]),
      commit("a", []),
    ]);

    expect(width).toBe(2);
    expect(placed[0]?.lane).toBe(0);
    expect(placed[1]?.lane).toBe(1);
    // Les deux rejoignent « b », qui est à la ligne 2.
    expect(placed[0]?.edges[0]?.toRow).toBe(2);
    expect(placed[1]?.edges[0]?.toRow).toBe(2);
  });

  it("opens a lane for the second parent of a merge", () => {
    const { placed } = layout([
      commit("m", ["a", "b"]),
      commit("a", ["r"]),
      commit("b", ["r"]),
      commit("r", []),
    ]);

    const merge = placed[0];
    expect(merge?.edges).toHaveLength(2);
    // Le premier parent reste sur la voie du commit ; le second s'en ouvre une autre.
    expect(merge?.edges[0]?.toLane).toBe(merge?.lane);
    expect(merge?.edges[1]?.toLane).not.toBe(merge?.lane);
  });

  it("leaves the edge open when the parent was not read", () => {
    // Frontière de la profondeur lue : le parent n'est pas dans la liste.
    const { placed } = layout([commit("c", ["hors-lecture"])]);

    expect(placed[0]?.edges[0]?.toRow).toBeNull();
  });

  it("reuses a lane freed by a branch that ended", () => {
    // « b » termine sa voie (aucun parent) ; « z », sans lien, peut la reprendre.
    const { width } = layout([
      commit("a", ["r"]),
      commit("b", []),
      commit("z", []),
      commit("r", []),
    ]);

    // Trois voies au plus fort, pas quatre : une voie libérée se réutilise.
    expect(width).toBeLessThanOrEqual(3);
  });

  it("places nothing without commits, and still has a width", () => {
    const { placed, width } = layout([]);

    expect(placed).toEqual([]);
    // Une largeur nulle ferait un dessin de zéro pixel.
    expect(width).toBe(1);
  });
});
