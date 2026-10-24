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
    // Les lignes vides et les espaces autour ne font pas une clé de plus.
    fill("Functional key", "$.code\n\n  ");
    fireEvent.click(screen.getByText("Add an indexable property"));
    fill("Name 1", "ville");
    fill("Path 1", "$.adresse.ville");
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
    expect(screen.getByLabelText("Functional key")).toHaveValue("$.code");

    fireEvent.click(screen.getByText("Remove indexable 1"));
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
