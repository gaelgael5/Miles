import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/sources";
const Q = "?branch=edition";
// Refondue le 25/10/2026 : la source dit OÙ ça va, et porte ses entrées.
const ENTRY = {
  kind: "web",
  source_model: "pudo/import-crm",
  chain: "comptes-import",
  modes: { element: true, batch: true, file: false },
  split: "",
  unified_transaction: false,
};
const SOURCE = { name: "crm", label: "CRM", storage: "sites", entries: [ENTRY] };
const BARE = { name: "crm", label: "CRM", storage: "sites", entries: [] };
const PICKERS = {
  [`GET /api/workspaces/retrait/storages${Q}`]: {
    status: 200,
    body: [{ name: "sites", label: "Sites", model: "shared/site", keys: ["$.code"] }],
  },
  [`GET /api/workspaces/retrait/data-models${Q}`]: {
    status: 200,
    body: [{ scope: "pudo", name: "import-crm", path: "domains/pudo/messages/import-crm.yaml" }],
  },
  [`GET /api/workspaces/retrait/transformations${Q}`]: {
    status: 200,
    body: [{ slug: "comptes-import", label: "Import des comptes", steps: 1 }],
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SourcesScreen", () => {
  it("saves on the label, the slug and the target data alone", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`POST ${ROUTE}${Q}`]: { status: 201, body: { ...BARE, rewrite_announced: false } },
      [`GET ${ROUTE}/crm${Q}`]: { status: 200, body: BARE },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition" });
    expect(await screen.findByText("No data source on this branch.")).toBeInTheDocument();

    fireEvent.click(screen.getByText("New source"));
    fill("Label", "CRM");
    expect(screen.getByLabelText("Name")).toHaveValue("crm");
    await screen.findByRole("option", { name: "Sites (shared/site)" });
    fill("Target data", "sites");
    // Les entrées ne sont pas proposées à la déclaration : la source s'enregistre d'abord.
    expect(screen.queryByText("Add a source")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Declare the source"));

    expect(await screen.findByText("sources/crm.yaml")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${ROUTE}${Q}`)?.body).toEqual(BARE);
  });

  it("shows every refusal with the entry rank it concerns", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`POST ${ROUTE}${Q}`]: {
        status: 422,
        body: {
          detail: {
            code: "source_invalide",
            problems: [
              { path: "storage", code: "storage_inconnu", detail: "absent" },
              { path: "entrees[0].modes", code: "aucun_mode", detail: null },
            ],
          },
        },
      },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition" });
    fireEvent.click(await screen.findByText("New source"));
    fill("Label", "CRM");
    fireEvent.submit(screen.getByRole("form", { name: "Declare the source" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("entrees[0].modes")).toBeInTheDocument();
    expect(alert).toHaveTextContent("Storage “absent” does not exist on this branch.");
    expect(alert).toHaveTextContent("At least one entry method must be ticked");
  });

  it("opens a source from its whole row, with no Open button", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}${Q}`]: {
        status: 200,
        body: [{ name: "crm", label: "CRM", storage: "sites", entries: 1 }],
      },
      [`GET ${ROUTE}/crm${Q}`]: { status: 200, body: SOURCE },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition" });

    expect(await screen.findByText("sources/crm.yaml")).toBeInTheDocument();
    expect(screen.getByText("1 entry")).toBeInTheDocument();
    expect(screen.queryByText("Open")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "CRM" }));

    expect(await screen.findByLabelText("Target data")).toBeInTheDocument();
  });
});

describe("the entries of a source (25/10/2026)", () => {
  function open(body: unknown = BARE) {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}/crm${Q}`]: { status: 200, body },
      [`PUT ${ROUTE}/crm${Q}`]: {
        status: 200,
        body: { ...SOURCE, rewrite_announced: true },
      },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition", source: "crm" });
    return calls;
  }

  it("adds a web entry, then asks for its model, its chain and its methods", async () => {
    const calls = open();
    expect(await screen.findByText(/No entry/)).toBeInTheDocument();

    // « on a un bouton ajouter une source. on clique puis on choisit entrée web ».
    fireEvent.click(screen.getByText("Add a source"));
    fireEvent.click(screen.getByRole("button", { name: "Web entry" }));

    await screen.findByRole("option", { name: "pudo/import-crm" });
    fill("Source model of entry 1", "pudo/import-crm");
    fill("Transformation chain of entry 1", "comptes-import");
    fireEvent.click(screen.getByLabelText(/Single element/));
    fireEvent.click(screen.getByLabelText(/Array — 200 elements at most/));
    fireEvent.click(screen.getByText("Save the source"));

    // La mutation est asynchrone : on attend son retour avant de lire l'appel.
    expect(await screen.findByText(/rewrite every object/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === `PUT ${ROUTE}/crm${Q}`)?.body).toEqual(SOURCE);
  });

  it("asks for the split path only when the file mode is ticked", async () => {
    open(SOURCE);
    expect(await screen.findByLabelText("Source model of entry 1")).toBeInTheDocument();
    expect(screen.queryByLabelText("Split path of entry 1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/File upload/));

    expect(screen.getByLabelText("Split path of entry 1")).toBeRequired();
  });

  it("removes an entry", async () => {
    open(SOURCE);
    expect(await screen.findByLabelText("Source model of entry 1")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Remove entry 1"));

    expect(screen.queryByLabelText("Source model of entry 1")).not.toBeInTheDocument();
    expect(screen.getByText(/No entry/)).toBeInTheDocument();
  });

  it("deletes the source after confirmation and returns to the list", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}/crm${Q}`]: { status: 200, body: SOURCE },
      [`DELETE ${ROUTE}/crm${Q}`]: { status: 204 },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition", source: "crm" });
    fireEvent.click(await screen.findByText("Delete the source"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Delete the source"));

    expect(await screen.findByText("No data source on this branch.")).toBeInTheDocument();
    expect(calls.some((c) => c.key === `DELETE ${ROUTE}/crm${Q}`)).toBe(true);
  });
});
