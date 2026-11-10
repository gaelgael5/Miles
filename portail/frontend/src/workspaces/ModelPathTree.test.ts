import { captionOf, lastSegment, selectable, treeOf } from "./ModelPathTree";
import { columnsSummary, indexName } from "./StorageIndexes";

function path(p: string, type = "string", format = "") {
  return { path: p, type, description: "", format };
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
  it("numbers each new index", () => {
    expect(indexName([])).toBe("index-1");
  });

  it("never proposes a name already taken, which would be refused on save", () => {
    expect(indexName(["index-1"])).toBe("index-2");
    expect(indexName(["index-1", "index-2"])).toBe("index-3");
  });
});

describe("columnsSummary", () => {
  it("shows the columns in order, which is the order of a composite index", () => {
    expect(columnsSummary(["$.adresse.ville", "$.code"], "vide")).toBe("ville · code");
  });

  it("montre le chemin entier des feuilles en collision, et elles seules", () => {
    // Le cas relevé par Gael le 01/11/2026 : « $.Email » et « $.Contact.Email » se
    // lisaient « Email · Email », ce qui fait croire qu'on a choisi deux fois la même.
    expect(columnsSummary(["$.Email", "$.Contact.Email", "$.code"], "vide")).toBe(
      "$.Email · $.Contact.Email · code",
    );
  });

  it("says plainly when an index has no column yet", () => {
    expect(columnsSummary([], "Aucune colonne")).toBe("Aucune colonne");
  });
});

describe("captionOf", () => {
  it("montre le format À CÔTÉ du type, jamais à sa place", () => {
    // Le défaut relevé par Gael le 10/11/2026 : l'arbre annonçait « string » d'un champ
    // que l'éditeur de modèle montre en « Date-Heure ». Les deux moitiés comptent — un
    // format qui REMPLACERAIT le type passerait un test qui ne vérifierait que lui.
    expect(captionOf("string", "date-time", "")).toBe("string · date-time");
  });

  it("se tait sur le format quand le schéma n'en déclare pas", () => {
    expect(captionOf("string", "", "")).toBe("string");
  });

  it("garde le titre après le type et son format", () => {
    expect(captionOf("string", "date-time", "Fin d'activité")).toBe(
      "string · date-time — Fin d'activité",
    );
  });

  it("garde le titre quand il n'y a pas de format", () => {
    expect(captionOf("integer", "", "Rang")).toBe("integer — Rang");
  });
});

describe("treeOf, le format", () => {
  it("porte le format du chemin jusqu'au nœud", () => {
    expect(treeOf([path("$.fin", "string", "date-time")])[0]?.format).toBe("date-time");
  });

  it("rabat sur le vide un chemin rendu sans format", () => {
    // La valeur vient du réseau : sans ce repli, la légende afficherait « undefined ».
    const sansFormat = { path: "$.code", type: "string", description: "" };
    expect(treeOf([sansFormat as never])[0]?.format).toBe("");
  });
});
