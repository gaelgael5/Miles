import { socleClash, socleNames, withoutSocle } from "./EventSocle";

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

// Un échantillon RÉEL, tel qu'un émetteur l'envoie : le socle commun, puis le métier.
// Les valeurs sont discriminantes — si le filtre ne faisait rien, « Montant » suffirait
// à rendre le test vert.
const DEDUIT = {
  type: "object",
  required: ["Name", "Montant"],
  properties: {
    Name: { type: "string" },
    ExternalId: { type: "string" },
    IntegrationDate: { type: "string" },
    Montant: { type: "number" },
    Dossier: { type: "string" },
  },
};

describe("withoutSocle", () => {
  it("retire les propriétés que le moteur décrit déjà, et dit lesquelles", () => {
    const [metier, retirees] = withoutSocle(DEDUIT, SOCLE);

    expect(Object.keys(metier["properties"] as object)).toEqual(["Montant", "Dossier"]);
    expect(retirees).toEqual(["Name", "ExternalId", "IntegrationDate"]);
  });

  it("les retire AUSSI des propriétés requises", () => {
    // Sans cela, `required: [Name]` resterait sur une propriété que le schéma ne déclare
    // plus : le moteur validerait le socle, puis exigerait un champ absent du métier.
    const [metier] = withoutSocle(DEDUIT, SOCLE);

    expect(metier["required"]).toEqual(["Montant"]);
  });

  it("laisse intact un schéma qui ne porte aucune propriété du socle", () => {
    const propre = { type: "object", properties: { Montant: { type: "number" } } };

    const [metier, retirees] = withoutSocle(propre, SOCLE);

    expect(metier).toEqual(propre);
    expect(retirees).toEqual([]);
  });

  it("rend le schéma tel quel quand il n'a pas de propriétés du tout", () => {
    // Un échantillon vide, ou une déduction qui n'a rien trouvé : pas de quoi lever.
    const [metier, retirees] = withoutSocle({ type: "object" }, SOCLE);

    expect(metier).toEqual({ type: "object" });
    expect(retirees).toEqual([]);
  });
});


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
  it("nomme les propriétés métier qui empiètent sur le socle", () => {
    const schema = {
      type: "object",
      properties: { Montant: { type: "number" }, ExternalId: { type: "integer" } },
    };

    expect(socleClash(schema, SOCLE)).toEqual(["ExternalId"]);
  });

  it("ne signale rien sur un schéma métier propre", () => {
    const schema = { type: "object", properties: { Montant: { type: "number" } } };

    expect(socleClash(schema, SOCLE)).toEqual([]);
  });
});
