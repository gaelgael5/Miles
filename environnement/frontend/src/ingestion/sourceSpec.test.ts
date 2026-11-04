import type { Method } from "../api/ingestion";
import { sourceSpecOf } from "./sourceSpec";

const MODELE = { type: "object", properties: { code: { type: "string" } } };
const SPEC = {
  info: { version: "1" },
  components: { securitySchemes: { cleApiEnEntete: { type: "apiKey" } } },
  paths: {
    "/ingest/{source}/{mode}": {
      post: {
        description: "Dépose un lot d'objets.",
        parameters: [
          { name: "source", in: "path", required: true },
          { name: "mode", in: "path", required: true },
          { name: "Idempotency-Key", in: "header", required: false },
        ],
        requestBody: { required: true, content: { "application/json": { schema: {} } } },
        responses: { "201": { description: "Lot reçu." } },
      },
    },
    "/ingest/{source}/fichier": {
      post: {
        description: "Dépose un document.",
        parameters: [{ name: "source", in: "path", required: true }],
        requestBody: {
          required: true,
          content: {
            "application/json": { schema: { type: "object" } },
            "application/octet-stream": { schema: { type: "string", format: "binary" } },
          },
        },
        responses: { "202": { description: "Pris en charge." } },
      },
    },
  },
};

function methode(mode: string, operation: string, example: unknown): Method {
  return {
    source: "sites",
    storage: "sites",
    entry_model: "pudo/site",
    mode,
    path: `/ingest/sites/${mode}`,
    operation,
    served: true,
    request_schema: MODELE,
    model_refusal: null,
    example,
  };
}

const ELEMENT = methode("element", "/ingest/{source}/{mode}", { code: "S-1" });
const TABLEAU = methode("tableau", "/ingest/{source}/{mode}", [{ code: "S-1" }]);
const FICHIER = methode("fichier", "/ingest/{source}/fichier", { sites: [{ code: "S-1" }] });
const AUTRE: Method = { ...TABLEAU, source: "comptes", path: "/ingest/comptes/tableau" };

/** Le corps JSON d'une adresse du document rendu. */
function corps(spec: Record<string, unknown>, chemin: string) {
  const chemins = spec.paths as Record<string, { post: Record<string, unknown> }>;
  const requestBody = chemins[chemin]?.post.requestBody as {
    content: Record<string, { schema?: unknown; example?: unknown }>;
  };
  return requestBody.content;
}

describe("le contrat publié restreint à une source", () => {
  it("substitue les adresses réelles de la source, et ignore celles des autres", () => {
    const rendu = sourceSpecOf(SPEC, [ELEMENT, TABLEAU, FICHIER, AUTRE], "sites");

    expect(Object.keys(rendu.paths as object)).toEqual([
      "/ingest/sites/element",
      "/ingest/sites/tableau",
      "/ingest/sites/fichier",
    ]);
  });

  it("garde ce que le contrat dit de lui-même, et ses schémas de sécurité", () => {
    // Recopier une description ici en aurait fait une seconde vérité : c'est le contrat
    // publié qui porte l'authentification et les garanties.
    const rendu = sourceSpecOf(SPEC, [ELEMENT], "sites");

    expect(rendu.info).toEqual(SPEC.info);
    expect(rendu.components).toEqual(SPEC.components);
  });

  it("retire les paramètres de CHEMIN, qui sont désormais écrits dans l'adresse", () => {
    const rendu = sourceSpecOf(SPEC, [TABLEAU], "sites");
    const post = (rendu.paths as Record<string, { post: { parameters: { name: string }[] } }>)[
      "/ingest/sites/tableau"
    ];

    // L'en-tête reste : il se présente toujours. Swagger demanderait sinon une valeur
    // pour un segment déjà posé.
    expect(post?.post.parameters.map((parametre) => parametre.name)).toEqual([
      "Idempotency-Key",
    ]);
  });

  it("annonce le modèle de l'entrée en corps d'un dépôt d'objet", () => {
    const rendu = sourceSpecOf(SPEC, [ELEMENT], "sites");

    const media = corps(rendu, "/ingest/sites/element")["application/json"];
    expect(media?.schema).toEqual(MODELE);
    expect(media?.example).toEqual({ code: "S-1" });
  });

  it("annonce un TABLEAU du modèle pour un dépôt de lot", () => {
    const rendu = sourceSpecOf(SPEC, [TABLEAU], "sites");

    expect(corps(rendu, "/ingest/sites/tableau")["application/json"]?.schema).toEqual({
      type: "array",
      items: MODELE,
    });
  });

  it("laisse au mode fichier le schéma du CONTRAT, parce que le modèle décrit les items", () => {
    // Le document a son découpage, et le modèle décrit ce qu'on trouve dedans. L'annoncer
    // comme corps serait faux — et un contrat faux coûte plus cher qu'un contrat vague.
    const rendu = sourceSpecOf(SPEC, [FICHIER], "sites");

    const contenu = corps(rendu, "/ingest/sites/fichier");
    expect(contenu["application/json"]?.schema).toEqual({ type: "object" });
    expect(contenu["application/json"]?.example).toEqual({ sites: [{ code: "S-1" }] });
    // Le dépôt d'un document binaire reste intact.
    expect(contenu["application/octet-stream"]?.schema).toEqual({
      type: "string",
      format: "binary",
    });
  });

  it("rend un document sans adresse quand la source n'a aucune méthode", () => {
    const rendu = sourceSpecOf(SPEC, [AUTRE], "sites");

    expect(rendu.paths).toEqual({});
  });
});
