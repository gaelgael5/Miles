import { socleClash, socleNames } from "./EventSocle";

// Le socle tel que le portail le sert : le JSON Schema de la racine commune de Miles —
// celle du moteur, surchargée de ce que Miles ajoute —, pas une liste de noms.
const SOCLE = {
  type: "object",
  required: ["Name"],
  properties: {
    Name: { type: "string", minLength: 1 },
    ExternalId: { type: "string" },
    IntegrationDate: { type: "string", format: "date-time", readOnly: true },
  },
};

describe("socleNames", () => {
  it("rend les propriétés que le moteur décrit déjà", () => {
    expect([...socleNames(SOCLE)].sort()).toEqual(["ExternalId", "IntegrationDate", "Name"]);
  });

  it("ne suppose rien quand le socle n'est pas encore lu", () => {
    // La requête est en vol au premier rendu : aucune collision ne doit être annoncée.
    expect(socleNames(undefined).size).toBe(0);
  });
});

describe("socleClash", () => {
  it("nomme les propriétés métier qui redéclarent une propriété du socle, dans l'ordre", () => {
    const schema = {
      type: "object",
      properties: { Montant: {}, ExternalId: {}, Name: {}, Reference: {} },
    };

    // DANS L'ORDRE du schéma, et les seules qui heurtent : un ordre d'ensemble ou une
    // liste complète enverrait corriger les mauvaises propriétés.
    expect(socleClash(SOCLE, schema)).toEqual(["ExternalId", "Name"]);
  });

  it("ne rend rien quand rien ne heurte, et ne lève pas sur un schéma sans propriétés", () => {
    // Discriminant : un `socleClash` qui rendrait toujours les noms du socle passerait
    // le test ci-dessus.
    expect(socleClash(SOCLE, { type: "object", properties: { Montant: {} } })).toEqual([]);
    expect(socleClash(SOCLE, { type: "object" })).toEqual([]);
    expect(socleClash(SOCLE, true)).toEqual([]);
    expect(socleClash(undefined, { properties: { Name: {} } })).toEqual([]);
  });
});
