import type { JsonSchema } from "jsonjoy-builder";

import { NO_USAGE, offerable, rootFields, toggled, usageOf, withUsage } from "./fieldUsage";

// Typé par le contrat : un jeu d'essai en `unknown` ou en littéral large est un
// compilateur qu'on a éteint (LESSONS.md, 29/10/2026).
const MODELE: JsonSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  type: "object",
  properties: {
    Id: { type: "string" },
    Postes: { type: "integer" },
    Adresse: { type: "object", properties: { Ville: { type: "string" } } },
    Tags: { type: "array", items: { type: "string" } },
    Contact: { $ref: "miles:/shared/contact" },
    Flou: { description: "sans type" },
  },
};

describe("les champs de premier niveau", () => {
  it("sont lus dans l'ordre du document, avec leur type", () => {
    expect(rootFields(MODELE).map((f) => [f.name, f.path, f.type])).toEqual([
      ["Id", "$.Id", "string"],
      ["Postes", "$.Postes", "integer"],
      ["Adresse", "$.Adresse", "object"],
      ["Tags", "$.Tags", "array"],
      ["Contact", "$.Contact", ""],
      ["Flou", "$.Flou", ""],
    ]);
  });

  it("ne descendent pas sous la racine", () => {
    // « Ville » est sous « Adresse » : c'est un chemin de filtre, et il se coche sur la
    // page d'un storage, pas ici.
    expect(rootFields(MODELE).map((f) => f.name)).not.toContain("Ville");
  });

  it("ne se cochent que s'ils portent UNE valeur", () => {
    // Le module d'environnement refuse une colonne sur un objet ou un tableau ; un
    // `$ref` n'est pas résolu ici, donc on ne promet rien sur ce qu'il désigne.
    const par = Object.fromEntries(rootFields(MODELE).map((f) => [f.name, offerable(f)]));
    expect(par).toEqual({
      Id: true,
      Postes: true,
      Adresse: false,
      Tags: false,
      Contact: false,
      Flou: false,
    });
  });

  it("sont vides sur un modèle qui ne décrit rien", () => {
    expect(rootFields({ type: "object" })).toEqual([]);
    expect(rootFields(true)).toEqual([]);
  });
});

describe("l'utilité déclarée", () => {
  it("est vide quand le modèle ne dit rien", () => {
    expect(usageOf(MODELE)).toEqual(NO_USAGE);
  });

  it("se lit sous le mot-clé d'extension", () => {
    const schema = { ...MODELE, "x-miles": { key: ["$.Id"], columns: ["$.Postes"] } };
    expect(usageOf(schema)).toEqual({ key: ["$.Id"], columns: ["$.Postes"] });
  });

  it("ignore ce qui a été écrit à la main hors forme", () => {
    // Le fichier s'édite aussi dans le YAML, et hors de Miles : une valeur qui n'est pas
    // une liste de chemins ne doit pas faire planter l'écran.
    const schema = { ...MODELE, "x-miles": { key: "Id", columns: [3, "$.Id"] } };
    expect(usageOf(schema)).toEqual({ key: [], columns: ["$.Id"] });
  });
});

describe("l'écriture de l'utilité", () => {
  it("pose le mot-clé sans toucher au reste du modèle", () => {
    const ecrit = withUsage(MODELE, { key: ["$.Id"], columns: ["$.Postes"] }) as Record<string, unknown>;
    expect(ecrit["x-miles"]).toEqual({ key: ["$.Id"], columns: ["$.Postes"] });
    expect(ecrit.properties).toBe(MODELE.properties);
    expect(ecrit.$schema).toBe(MODELE.$schema);
  });

  it("élague les champs qui n'existent plus", () => {
    // Le champ a été supprimé dans l'éditeur : son utilité ne décrit plus rien, et la
    // garder la ferait revivre le jour où un champ du même nom revient.
    const ecrit = withUsage(MODELE, {
      key: ["$.Id", "$.Parti"],
      columns: ["$.Parti"],
    }) as Record<string, unknown>;
    // Les deux listes restent écrites, même vides : le fichier a toujours la même
    // forme, et qui le lit n'a pas à distinguer « aucune colonne » de « pas déclaré ».
    expect(ecrit["x-miles"]).toEqual({ key: ["$.Id"], columns: [] });
  });

  it("retire le mot-clé quand plus rien n'est déclaré", () => {
    const pose = withUsage(MODELE, { key: ["$.Id"], columns: [] });
    const retire = withUsage(pose, { key: [], columns: [] }) as Record<string, unknown>;
    expect("x-miles" in retire).toBe(false);
  });

  it("garde l'ordre des parties de la clé", () => {
    // La clé fonctionnelle est composite : `["A-1", "FRA"]` n'est pas `["FRA", "A-1"]`.
    const un = toggled([], "$.Postes");
    const deux = toggled(un, "$.Id");
    expect(deux).toEqual(["$.Postes", "$.Id"]);
    expect(toggled(deux, "$.Postes")).toEqual(["$.Id"]);
  });
});
