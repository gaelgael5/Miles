import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, modelListing, renderWorkspaces } from "./workspaceFixtures";

// Éditeur visuel JSONJoy et YAML, synchronisés, en mémoire jusqu'à « Enregistrer » (e38806f3).
const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/data-models";
const MODEL = {
  scope: "shared",
  name: "personne",
  path: "shared/models/personne.yaml",
  label: "Personne",
  version: 3,
};
const ADRESSE = { ...MODEL, name: "adresse", path: "shared/models/adresse.yaml", label: "Adresse", version: 1 };
const YAML =
  "$schema: https://json-schema.org/draft/2020-12/schema\n$id: miles:/shared/personne\n" +
  "title: Personne\ntype: object\nproperties:\n  nom:\n    type: string\n";

afterEach(() => {
  vi.unstubAllGlobals();
});

function open(routes: Record<string, unknown> = {}, held = true) {
  const calls = mockApi({
    ...(held ? HELD : { "GET /api/workspaces/retrait/holds": { status: 200, body: [] } }),
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    [`GET ${ROUTE}/shared/personne?branch=edition`]: { status: 200, body: { ...MODEL, content: YAML } },
    [`GET ${ROUTE}?branch=edition`]: { status: 200, body: modelListing([MODEL, ADRESSE]) },
    ...routes,
  } as Parameters<typeof mockApi>[0]);
  renderWorkspaces({ id: "retrait", view: "dataModels", branch: "edition", model: "shared/personne" });
  return calls;
}

describe("schema editor", () => {
  it("shows the visual editor and the YAML side by side, with the system's version", async () => {
    open();

    // Premier chargement différé de JSONJoy dans la suite : plus lent que les suivants.
    expect(await screen.findByLabelText("YAML", {}, { timeout: 10_000 })).toHaveValue(YAML);
    expect(screen.getByRole("region", { name: "Visual editor" })).toBeInTheDocument();
    expect(await screen.findByText("nom")).toBeInTheDocument();
    expect(screen.getByText("version 3")).toBeInTheDocument();
  });

  it("offers the visible models as references, with their URI", async () => {
    open();
    await screen.findByLabelText("YAML");

    const summary = await screen.findByText("Referenceable models");
    const references = summary.closest("details") as HTMLElement;
    expect(within(references).getByText("miles:/shared/adresse")).toBeInTheDocument();
    expect(within(references).queryByText("miles:/shared/personne")).toBeNull();
  });

  it("follows the YAML in memory, and says where unreadable YAML breaks", async () => {
    const calls = open();
    const yaml = await screen.findByLabelText("YAML");

    fireEvent.change(yaml, { target: { value: YAML + "  age:\n    type: integer\n" } });
    expect(await screen.findByText("age")).toBeInTheDocument();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    fireEvent.change(yaml, { target: { value: "type: object\nproperties: [\n" } });

    expect(screen.getByRole("note")).toHaveTextContent("Unreadable YAML");
    expect(calls.some((c) => c.key.startsWith("PUT"))).toBe(false);
  });

  it("follows a change of an existing property made in the YAML", async () => {
    open();
    const yaml = await screen.findByLabelText("YAML");
    const described = YAML + "    description: Ancienne\n";
    fireEvent.change(yaml, { target: { value: described } });
    expect(await screen.findByText("Ancienne")).toBeInTheDocument();

    fireEvent.change(yaml, { target: { value: described.replace("Ancienne", "Nouvelle") } });

    expect(await screen.findByText("Nouvelle")).toBeInTheDocument();
    expect(screen.queryByText("Ancienne")).toBeNull();
  });

  it("saves the schema, and asks before leaving unsaved work", async () => {
    const changed = YAML + "  age:\n    type: integer\n";
    const calls = open({
      [`PUT ${ROUTE}/shared/personne?branch=edition`]: { status: 200, body: { ...MODEL, version: 4 } },
    });
    fireEvent.change(await screen.findByLabelText("YAML"), { target: { value: changed } });

    fireEvent.click(screen.getByRole("button", { name: "← Back to models" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("they will be lost");
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await vi.waitFor(() =>
      expect(calls.find((c) => c.key.startsWith("PUT"))?.body).toEqual({ content: changed }),
    );
  });

  it("is read-only without the hold", async () => {
    open({}, false);

    expect(await screen.findByLabelText("YAML")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });
});

/**
 * Le socle verrouillé AU-DESSUS des champs métier, quand une déclaration désigne ce
 * modèle (story 8a9ff6bc, critère 3).
 *
 * Il avait disparu de l'écran le 14/11/2026 avec l'éditeur de schéma d'event ; il revient
 * là où le modèle s'édite vraiment. Ce qui le déclenche, c'est l'USAGE du modèle — un
 * `DEFINE EVENT` le nomme —, jamais son nom ni son dossier.
 */
const SOCLE = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  title: "urban-workflow base event",
  type: "object",
  required: ["Name"],
  properties: { Name: { type: "string" }, ExternalId: { type: "string" } },
};
const AS_EVENT = {
  kind: "event_type",
  name: "personne_vue",
  label: "Personne vue",
  path: "shared/shared.wf",
  part: null,
};
const SOCLE_ROUTE = "GET /api/workspaces/retrait/workflow-events/socle?branch=edition";

function openAsPayload(usages: object[], routes: Record<string, unknown> = {}) {
  return open({
    [`GET ${ROUTE}?branch=edition`]: {
      status: 200,
      body: { models: [{ ...MODEL, usages }, { ...ADRESSE, usages: [] }], broken: [] },
    },
    [SOCLE_ROUTE]: { status: 200, body: SOCLE },
    ...routes,
  });
}

describe("a model a DEFINE EVENT designates", () => {
  it("mounts the engine's base type above the business fields, locked", async () => {
    openAsPayload([AS_EVENT]);

    expect(await screen.findByText("Engine base type", {}, { timeout: 10_000 })).toBeInTheDocument();
    // Les propriétés du socle, dans le MÊME éditeur : montré autrement, il se lirait
    // comme une annexe et on ne verrait plus que le type d'event en DÉRIVE.
    expect(await screen.findByText("ExternalId")).toBeInTheDocument();
  });

  it("says nothing of the socle on a model no declaration designates", async () => {
    // Discriminant : sans ce contrôle, un socle affiché toujours passerait le test
    // ci-dessus — et il ferait croire que la règle vaut pour tout modèle.
    const calls = openAsPayload([]);
    await screen.findByLabelText("YAML", {}, { timeout: 10_000 });

    expect(screen.queryByText("Engine base type")).not.toBeInTheDocument();
    // Et le socle n'est même pas DEMANDÉ : la règle ne s'applique pas ici.
    expect(calls.some((c) => c.key === SOCLE_ROUTE)).toBe(false);
  });

  it("warns, while typing, on a business property that clashes with the socle", async () => {
    openAsPayload([AS_EVENT]);
    const yaml = await screen.findByLabelText("YAML", {}, { timeout: 10_000 });

    fireEvent.change(yaml, { target: { value: YAML + "  ExternalId:\n    type: integer\n" } });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/ExternalId/);
    expect(alert).toHaveTextContent(/unsatisfiable/);
  });
});
