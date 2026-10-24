import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/storages";
const Q = "?branch=edition";
const STORAGE = {
  name: "sites",
  label: "Sites",
  model: "shared/site",
  keys: ["$.code"],
  indexables: [{ name: "ville", jpath: "$.adresse.ville" }],
};
const MODELS = {
  [`GET /api/workspaces/retrait/data-models${Q}`]: {
    status: 200,
    body: [{ scope: "shared", name: "site", path: "data-models/shared/site.yaml" }],
  },
  // L'arbre se coche : il vient de la route des chemins, celle de l'intellisense JSLT.
  [`GET /api/workspaces/retrait/data-models/shared/site/paths${Q}`]: {
    status: 200,
    body: {
      paths: [
        { path: "$.code", type: "string", description: "" },
        { path: "$.adresse", type: "object", description: "" },
        { path: "$.adresse.ville", type: "string", description: "Ville" },
        { path: "$.enseignes", type: "array", description: "" },
        { path: "$.enseignes[0]", type: "string", description: "" },
      ],
    },
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StoragesScreen (24/10/2026)", () => {
  it("declares a storage with its model, functional key and indexable properties", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`POST ${ROUTE}${Q}`]: { status: 201, body: { ...STORAGE, rewrite_announced: false } },
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: STORAGE },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition" });
    expect(await screen.findByText("No storage on this branch.")).toBeInTheDocument();

    fireEvent.click(screen.getByText("New storage"));
    // Le libellé est libre ; l'identifiant s'en déduit — « Sites » ne se fait pas refuser
    // sur sa majuscule (Gael, 24/10/2026).
    fill("Label", "Sites");
    expect(screen.getByLabelText("Name")).toHaveValue("sites");
    await screen.findByRole("option", { name: "shared/site" });
    fill("Object model", "shared/site");

    // L'arbre n'est pas affiché : c'est le champ qui l'ouvre (Gael, 24/10/2026).
    expect(screen.queryByRole("list", { name: "Functional key" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Functional key" }));
    const keyTree = await screen.findByRole("list", { name: "Functional key" });
    fireEvent.click(within(keyTree).getByRole("checkbox", { name: /code/ }));
    // Cocher ne referme pas : la sélection est multiple.
    expect(screen.getByRole("list", { name: "Functional key" })).toBeInTheDocument();
    fireEvent.click(screen.getByText("Done"));

    fireEvent.click(screen.getByRole("button", { name: "Indexable properties" }));
    const indexTree = await screen.findByRole("list", { name: "Indexable properties" });
    fireEvent.click(within(indexTree).getByRole("checkbox", { name: /ville/ }));
    // Le nom d'index est proposé depuis le dernier segment du chemin.
    expect(screen.getByLabelText("Name 1")).toHaveValue("ville");
    fireEvent.click(screen.getByText("Declare the storage"));

    expect(await screen.findByText("storages/sites.yaml")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${ROUTE}${Q}`)?.body).toEqual(STORAGE);
  });

  it("shows every refusal with the path it concerns", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`POST ${ROUTE}${Q}`]: {
        status: 422,
        body: {
          detail: {
            code: "storage_invalide",
            problems: [
              { path: "indexables[0].jpath", code: "tableau_interdit", detail: "$.enseignes" },
              { path: "cle[0]", code: "propriete_inconnue", detail: "$.rien" },
            ],
          },
        },
      },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition" });
    fireEvent.click(await screen.findByText("New storage"));
    fill("Label", "Sites");
    fireEvent.submit(screen.getByRole("form", { name: "Declare the storage" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("indexables[0].jpath")).toBeInTheDocument();
    expect(alert).toHaveTextContent("“$.enseignes” designates an array");
    expect(alert).toHaveTextContent("“$.rien” designates nothing in the storage model.");
  });

  it("lists a storage with its model and its key", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}${Q}`]: {
        status: 200,
        body: [{ name: "sites", label: "Sites", model: "shared/site", keys: ["$.code"] }],
      },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition" });

    expect(await screen.findByText("storages/sites.yaml")).toBeInTheDocument();
    expect(screen.getByText("Sites")).toBeInTheDocument();
    expect(screen.getByText("shared/site")).toBeInTheDocument();
    expect(screen.getByText("$.code")).toBeInTheDocument();
  });
});

describe("StorageScreen (24/10/2026)", () => {
  it("keeps the name frozen and announces the rewrite a change will cause", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: STORAGE },
      [`PUT ${ROUTE}/sites${Q}`]: {
        status: 200,
        body: { ...STORAGE, indexables: [], rewrite_announced: true },
      },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition", storage: "sites" });
    expect(await screen.findByLabelText("Name")).toBeDisabled();
    expect(screen.getByLabelText("Label")).toHaveValue("Sites");

    // Décocher la propriété indexable la retire, comme la cocher l'avait ajoutée.
    fireEvent.click(screen.getByRole("button", { name: "Indexable properties" }));
    const indexTree = await screen.findByRole("list", { name: "Indexable properties" });
    fireEvent.click(within(indexTree).getByRole("checkbox", { name: /ville/ }));
    fireEvent.click(screen.getByText("Save the storage"));

    expect(await screen.findByText(/rewrite every object and its index/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === `PUT ${ROUTE}/sites${Q}`)?.body).toEqual({
      ...STORAGE,
      indexables: [],
    });
  });

  it("names the sources that keep a storage from being deleted", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: STORAGE },
      [`DELETE ${ROUTE}/sites${Q}`]: {
        status: 409,
        body: { detail: { code: "storage_utilise", sources: ["crm", "legacy"] } },
      },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition", storage: "sites" });
    fireEvent.click(await screen.findByText("Delete the storage"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Delete the storage"));

    expect(await screen.findByText(/crm, legacy/)).toBeInTheDocument();
  });

  it("deletes a free storage after confirmation and returns to the list", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: STORAGE },
      [`DELETE ${ROUTE}/sites${Q}`]: { status: 204 },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition", storage: "sites" });
    fireEvent.click(await screen.findByText("Delete the storage"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Delete the storage"));

    expect(await screen.findByText("No storage on this branch.")).toBeInTheDocument();
    expect(calls.some((c) => c.key === `DELETE ${ROUTE}/sites${Q}`)).toBe(true);
  });
});

describe("the property tree (24/10/2026)", () => {
  it("offers only values, never an array, an object or a path through an array", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition" });
    fireEvent.click(await screen.findByText("New storage"));
    fill("Label", "Sites");
    await screen.findByRole("option", { name: "shared/site" });
    fill("Object model", "shared/site");

    fireEvent.click(screen.getByRole("button", { name: "Functional key" }));
    const tree = await screen.findByRole("list", { name: "Functional key" });
    const names = within(tree)
      .getAllByRole("checkbox")
      .map((box) => box.closest("label")?.textContent ?? "");

    // « adresse » (objet) et « enseignes » (tableau) se lisent mais ne se cochent pas ;
    // « [0] » traverse un tableau, donc ne désigne pas une valeur unique.
    expect(names.some((n) => n.includes("code"))).toBe(true);
    expect(names.some((n) => n.includes("ville"))).toBe(true);
    expect(names.some((n) => n.startsWith("adresse"))).toBe(false);
    expect(names.some((n) => n.startsWith("enseignes"))).toBe(false);
    expect(names.some((n) => n.includes("[0]"))).toBe(false);
    // Elles restent affichées : c'est le chemin pour atteindre leurs enfants.
    expect(within(tree).getByTitle("$.adresse")).toBeInTheDocument();
  });

  it("says what to do when no model is chosen yet", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition" });
    fireEvent.click(await screen.findByText("New storage"));
    fireEvent.click(screen.getByRole("button", { name: "Functional key" }));

    expect(screen.getByText(/Choose the object model first/)).toBeInTheDocument();
  });
});

describe("the picker field (24/10/2026)", () => {
  function open() {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: STORAGE },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition", storage: "sites" });
  }

  it("shows what is selected while closed", async () => {
    open();

    expect(await screen.findByRole("button", { name: "Functional key" })).toHaveTextContent(
      "$.code",
    );
    expect(screen.getByRole("button", { name: "Indexable properties" })).toHaveTextContent(
      "$.adresse.ville",
    );
  });

  it("closes on Escape without losing what was ticked", async () => {
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Functional key" }));
    await screen.findByRole("list", { name: "Functional key" });

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("list", { name: "Functional key" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Functional key" })).toHaveTextContent("$.code");
  });

  it("closes when the click lands outside it", async () => {
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Functional key" }));
    await screen.findByRole("list", { name: "Functional key" });

    fireEvent.mouseDown(document.body);

    expect(screen.queryByRole("list", { name: "Functional key" })).not.toBeInTheDocument();
  });
});
