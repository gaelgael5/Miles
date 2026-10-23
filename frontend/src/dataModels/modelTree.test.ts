import {
  addProperty,
  parseModel,
  removeProperty,
  retypeProperty,
  serializeModel,
  updateProperty,
} from "./modelTree";

const COLIS = `nom: colis
version: 2
description: Colis tel que le terminal le manipule
proprietes:
  reference:
    type: chaine
    obligatoire: true
  etat:
    type: enumeration
    valeurs:
      - depose
      - remis
  destinataire:
    type: objet
    modele: personne
  etiquettes:
    type: liste
    elements:
      type: liste
      elements:
        type: chaine
`;

function doc(text: string) {
  const parsed = parseModel(text);
  if (!parsed.ok) throw new Error(JSON.stringify(parsed));
  return parsed.doc;
}

describe("modelTree", () => {
  it("reads a model and writes it back unchanged", () => {
    const read = doc(COLIS);

    expect(read.proprietes.map((p) => [p.name, p.type, p.obligatoire])).toEqual([
      ["reference", "chaine", true],
      ["etat", "enumeration", false],
      ["destinataire", "objet", false],
      ["etiquettes", "liste", false],
    ]);
    expect(serializeModel(read)).toBe(COLIS);
  });

  it("writes an empty draft with empty properties", () => {
    const draft = doc("nom: m\nversion: 1\nproprietes: {}\n");

    expect(draft.proprietes).toEqual([]);
    expect(serializeModel(draft)).toBe("nom: m\nversion: 1\nproprietes: {}\n");
  });

  it("adds, retypes, renames and removes a property in memory", () => {
    let edited = addProperty(doc("nom: m\nversion: 1\nproprietes: {}\n"));
    const id = edited.proprietes[0]?.id ?? "";
    edited = updateProperty(edited, id, { name: "statut", obligatoire: true });
    edited = retypeProperty(edited, id, "enumeration");
    edited = updateProperty(edited, id, { valeurs: ["ouvert", "clos"] });

    expect(serializeModel(edited)).toBe(
      "nom: m\nversion: 1\nproprietes:\n  statut:\n    type: enumeration\n    valeurs:\n" +
        "      - ouvert\n      - clos\n    obligatoire: true\n",
    );
    // Changer de type ne garde rien de l'ancien : pas de `valeurs` sur un booléen.
    expect(serializeModel(retypeProperty(edited, id, "booleen"))).not.toContain("valeurs");
    expect(removeProperty(edited, id).proprietes).toEqual([]);
  });

  it("names the next free property", () => {
    const once = addProperty(doc("nom: m\nversion: 1\nproprietes: {}\n"));
    const twice = addProperty(once);

    expect(twice.proprietes.map((p) => p.name)).toEqual(["propriete_1", "propriete_2"]);
  });

  it("gives the position of unreadable YAML", () => {
    const parsed = parseModel("nom: m\nproprietes:\n  a: [chaine\n");

    expect(parsed.ok).toBe(false);
    expect(parsed.ok === false && parsed.reason === "syntax" && parsed.line).toBeGreaterThan(0);
  });

  it("refuses to open on what it cannot write back, naming where", () => {
    expect(parseModel("nom: m\nversion: 1\nautre: x\nproprietes: {}\n")).toEqual({
      ok: false,
      reason: "shape",
      path: "autre",
    });
    expect(parseModel("nom: m\nversion: 1\nproprietes:\n  a:\n    type: texte\n")).toEqual({
      ok: false,
      reason: "shape",
      path: "proprietes.a.type",
    });
  });

  it("refuses duplicate keys rather than keeping the last one", () => {
    const parsed = parseModel("nom: m\nversion: 1\nproprietes:\n  a:\n    type: chaine\n  a:\n    type: entier\n");

    expect(parsed.ok).toBe(false);
  });
});
