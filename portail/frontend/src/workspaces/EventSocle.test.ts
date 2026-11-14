import { socleNames } from "./EventSocle";

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
