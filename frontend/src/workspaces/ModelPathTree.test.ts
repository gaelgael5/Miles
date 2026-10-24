import { lastSegment, selectable, treeOf } from "./ModelPathTree";
import { indexName } from "./StorageForm";

function path(p: string, type = "string") {
  return { path: p, type, description: "" };
}

describe("treeOf", () => {
  it("nests each path under the longest prefix already seen", () => {
    const roots = treeOf([
      path("$.code"),
      path("$.adresse", "object"),
      path("$.adresse.ville"),
      path("$.adresse.pays"),
    ]);

    expect(roots.map((n) => n.path)).toEqual(["$.code", "$.adresse"]);
    expect(roots[1]?.children.map((n) => n.path)).toEqual([
      "$.adresse.ville",
      "$.adresse.pays",
    ]);
  });

  it("puts an array item under its array, not beside it", () => {
    const roots = treeOf([
      path("$.lignes", "array"),
      path("$.lignes[0]", "object"),
      path("$.lignes[0].ref"),
    ]);

    expect(roots).toHaveLength(1);
    expect(roots[0]?.children[0]?.path).toBe("$.lignes[0]");
    expect(roots[0]?.children[0]?.children[0]?.path).toBe("$.lignes[0].ref");
  });

  it("gives nothing for nothing", () => {
    expect(treeOf([])).toEqual([]);
  });
});

describe("selectable", () => {
  it("takes a value", () => {
    expect(selectable("string", "$.code")).toBe(true);
    expect(selectable("integer", "$.rang")).toBe(true);
  });

  it("refuses a container, which carries no single value to compare or index", () => {
    expect(selectable("array", "$.lignes")).toBe(false);
    expect(selectable("object", "$.adresse")).toBe(false);
  });

  it("refuses a path that crosses an array, which the backend rejects too", () => {
    // Le backend rend « chemin_de_propriete_attendu » : on ne le propose donc jamais.
    expect(selectable("string", "$.lignes[0].ref")).toBe(false);
  });
});

describe("lastSegment", () => {
  it.each([
    ["$.a.b", "b"],
    ["$.a", "a"],
    ["$.l[0]", "[0]"],
    ["$.l[0].ref", "ref"],
    ["$", "$"],
  ])("reads %s as %s", (given, expected) => {
    expect(lastSegment(given)).toBe(expected);
  });
});

describe("indexName", () => {
  it("proposes the last segment of the path", () => {
    expect(indexName("$.adresse.ville", [])).toBe("ville");
  });

  it("never proposes a name already taken, which would be refused on save", () => {
    expect(indexName("$.adresse.ville", ["ville"])).toBe("ville-2");
    expect(indexName("$.adresse.ville", ["ville", "ville-2"])).toBe("ville-3");
  });

  it("never proposes a name the rule would refuse", () => {
    // Deux caractères minimum : « a » serait rejeté en « nom_invalide » à l'enregistrement.
    expect(indexName("$.a", [])).toBe("propriete");
    expect(indexName("$.[0]", [])).toBe("propriete");
  });
});
