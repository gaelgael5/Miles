import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/workflow-events";
const MODELS = "/api/workspaces/retrait/data-models";
const DOMAINS = "/api/workspaces/retrait/domains";
const NO_VERSION = {
  "GET /api/workspaces/retrait/versions?branch=edition": { status: 200, body: [] },
};
// Un type d'event tel que le portail le sert : une DÉCLARATION, pas un document.
const DEMANDE = {
  scope: "shared",
  name: "demande_soumise",
  label: "Demande soumise",
  model: "shared/models/demande.yaml",
  model_scope: "shared",
  model_name: "demande",
  // L'ordre est DISCRIMINANT : un tri à l'affichage changerait le dédoublonnage.
  unique: ["Tracking", "ExternalId"],
  model_missing: false,
};
const DEMANDE_MODEL = {
  scope: "shared",
  name: "demande",
  path: "shared/models/demande.yaml",
  label: "Demande",
  version: 1,
};
// Tel que le portail le sert : le JSON Schema du moteur, pas une liste de noms.
const SOCLE = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  title: "urban-workflow base event",
  type: "object",
  required: ["Name"],
  properties: {
    Name: { type: "string", minLength: 1 },
    ExternalId: { type: "string" },
  },
};

function routes(extra: Record<string, unknown> = {}) {
  return {
    ...HELD,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    ...NO_VERSION,
    [`GET ${ROUTE}?branch=edition`]: { status: 200, body: [DEMANDE] },
    [`GET ${ROUTE}/socle?branch=edition`]: { status: 200, body: SOCLE },
    [`GET ${MODELS}?branch=edition`]: { status: 200, body: [DEMANDE_MODEL] },
    [`GET ${DOMAINS}?branch=edition`]: { status: 200, body: [{ name: "achats" }] },
    ...extra,
  } as never;
}

async function openEvents(extra: Record<string, unknown> = {}) {
  const calls = mockApi(routes(extra));
  renderWorkspaces({ id: "retrait", view: "events", branch: "edition" });
  await screen.findByRole("heading", { name: "Event types — Retrait de colis" });
  return calls;
}

/**
 * Attend que la liste des modèles soit arrivée avant de choisir le payload.
 *
 * Sans cette attente, le `<select>` existe déjà mais sans ses options : la valeur posée
 * ne correspond à aucune, le navigateur la laisse vide, et le champ étant obligatoire la
 * soumission ne part pas — un échec qui n'accuse pas sa cause. Mesuré en écrivant ce
 * fichier le 14/11/2026.
 */
async function pickModel(value = "shared/demande") {
  await screen.findByRole("option", { name: /shared\/models\/demande\.yaml/ });
  fireEvent.change(screen.getByLabelText("Payload model"), { target: { value } });
}

describe("the event type referential", () => {
  it("lists each declaration with the DSL name, its payload and its keys IN ORDER", async () => {
    await openEvents();

    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    // Le NOM du DSL : la seule chose qu'un script de workflow connaisse de cet écran.
    expect(within(row).getByText("demande_soumise")).toBeInTheDocument();
    expect(within(row).getByText("shared/models/demande.yaml")).toBeInTheDocument();
    // L'ordre tel qu'il a été saisi, et pas trié : le moteur en dérive le hash
    // d'anti-doublon par concaténation.
    expect(within(row).getByText("Tracking, ExternalId")).toBeInTheDocument();
  });

  it("proposes an underscored name, because the engine's DSL rejects hyphens", async () => {
    // La règle est MESURÉE (urban-workflow 0.2.1, 11/11/2026) : sans ce remplacement,
    // « Demande soumise » proposerait « demande-soumise », refusé par le serveur.
    await openEvents();
    fireEvent.click(await screen.findByText("Declare an event type"));

    fill("Label", "Demande soumise");

    expect(screen.getByLabelText("DSL name")).toHaveValue("demande_soumise");
  });

  it("declares the type with its payload model and its ordered keys", async () => {
    const calls = await openEvents({
      [`POST ${ROUTE}/declarations?branch=edition`]: { status: 201, body: DEMANDE },
    });
    fireEvent.click(await screen.findByText("Declare an event type"));
    fill("Label", "Demande soumise");
    await pickModel();
    fill("Uniqueness keys", " Tracking , ExternalId ");
    fireEvent.click(screen.getByRole("button", { name: "Declare the event type" }));

    await screen.findByText("Declare an event type");
    expect(calls.find((c) => c.key === `POST ${ROUTE}/declarations?branch=edition`)?.body).toEqual({
      scope: "shared",
      label: "Demande soumise",
      slug: "demande_soumise",
      model_scope: "shared",
      model_name: "demande",
      // Les espaces de saisie retirés, l'ORDRE conservé.
      unique: ["Tracking", "ExternalId"],
    });
  });

  it("names the base properties a uniqueness key may use without being in the model", async () => {
    // `ExternalId` est la clé d'anti-doublon la plus courante et ne vient pas du modèle :
    // sans cette aide, la personne essaie, se fait refuser, et ne sait pas quoi écrire.
    await openEvents();
    fireEvent.click(await screen.findByText("Declare an event type"));

    expect(await screen.findByText(/ExternalId, Name/)).toBeInTheDocument();
  });

  it("says why a name the DSL would reject is refused", async () => {
    await openEvents({
      [`POST ${ROUTE}/declarations?branch=edition`]: {
        status: 422,
        body: { detail: { field: "name" } },
      },
    });
    fireEvent.click(await screen.findByText("Declare an event type"));
    fill("Label", "Demande");
    fill("DSL name", "demande-soumise");
    await pickModel();
    fireEvent.click(screen.getByRole("button", { name: "Declare the event type" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/rejects hyphens/);
  });

  it("names the rule the designated model breaks, rather than « not conforming »", async () => {
    await openEvents({
      [`POST ${ROUTE}/declarations?branch=edition`]: {
        status: 422,
        body: {
          detail: {
            code: "declaration_non_conforme",
            problems: [{ path: "additionalProperties", code: "schema_ferme", detail: null }],
          },
        },
      },
    });
    fireEvent.click(await screen.findByText("Declare an event type"));
    fill("Label", "Demande");
    await pickModel();
    fireEvent.click(screen.getByRole("button", { name: "Declare the event type" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/cannot carry an event type/);
    expect(alert).toHaveTextContent(/no real payload would pass/);
  });

  it("flags a declaration whose payload model has disappeared", async () => {
    // C'est ce qui bloque l'enregistrement d'une version : le dire ICI, c'est le dire là
    // où on peut la corriger.
    await openEvents({
      [`GET ${ROUTE}?branch=edition`]: {
        status: 200,
        body: [{ ...DEMANDE, model_missing: true }],
      },
    });

    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    expect(within(row).getByText("model missing")).toBeInTheDocument();
  });

  it("does not flag a declaration whose model is there", async () => {
    // Discriminant : sans ce contrôle, un badge affiché toujours passerait le test ci-dessus.
    await openEvents();

    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    expect(within(row).queryByText("model missing")).not.toBeInTheDocument();
  });

  it("opens the payload in the MODEL screen, since it is an ordinary model", async () => {
    await openEvents({
      [`GET ${MODELS}/shared/demande?branch=edition`]: {
        status: 200,
        body: { ...DEMANDE_MODEL, content: "title: Demande\ntype: object\nproperties: {}\n" },
      },
    });
    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;

    fireEvent.click(within(row).getByText("shared/models/demande.yaml"));

    // L'éditeur de schéma d'event n'existe plus : c'est l'écran des modèles qui édite.
    expect(await screen.findByRole("heading", { name: "Demande" })).toBeInTheDocument();
  });

  it("changes the label, the model and the keys WITHOUT sending the name", async () => {
    const calls = await openEvents({
      [`PUT ${ROUTE}/shared/demande_soumise?branch=edition`]: { status: 200, body: DEMANDE },
    });
    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Edit" }));
    await pickModel();

    fill("Label", "Demande reçue");
    fill("Uniqueness keys", "ExternalId");
    fireEvent.click(screen.getByRole("button", { name: "Save the declaration" }));

    await screen.findByRole("button", { name: "Edit" });
    const sent = calls.find((c) => c.key === `PUT ${ROUTE}/shared/demande_soumise?branch=edition`);
    expect(sent?.body).toEqual({
      label: "Demande reçue",
      model_scope: "shared",
      model_name: "demande",
      unique: ["ExternalId"],
    });
  });

  it("reports an unreadable artefact at the engine's own position", async () => {
    // Retouché hors de Miles, ou produit par un autre outil : le moteur refuserait de
    // charger tout le répertoire. Un « fichier invalide » sans position ne se corrige pas.
    await openEvents({
      [`GET ${ROUTE}?branch=edition`]: {
        status: 422,
        body: {
          detail: {
            code: "artefact_illisible",
            problems: [{ line: 2, column: 13, message: "mismatched input ';'" }],
          },
        },
      },
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/would refuse to load the whole directory/);
    expect(alert).toHaveTextContent(/line 2, column 13/);
    expect(alert).toHaveTextContent(/mismatched input/);
  });
});
