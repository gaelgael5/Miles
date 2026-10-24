import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/sources";
const Q = "?branch=edition";
// Depuis la séparation du 24/10/2026 (844f15ad), la source désigne un storage et ne
// porte plus ni modèle, ni clé, ni propriétés filtrables.
const SOURCE = {
  name: "crm",
  label: "CRM",
  storage: "sites",
  source_model: "pudo/import-crm",
  split: "$.accounts[*]",
  chain: "comptes-import",
  large_file: true,
  unified_transaction: false,
};
const PICKERS = {
  [`GET /api/workspaces/retrait/storages${Q}`]: {
    status: 200,
    body: [{ name: "sites", label: "Sites", model: "shared/site", keys: ["$.code"] }],
  },
  [`GET /api/workspaces/retrait/data-models${Q}`]: {
    status: 200,
    // Un nom à tiret, comme « pudo/import-crm » : le motif de référence le refusait.
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
  it("declares a source that designates its storage and chain, then opens it", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`POST ${ROUTE}${Q}`]: { status: 201, body: { ...SOURCE, rewrite_announced: false } },
      [`GET ${ROUTE}/crm${Q}`]: { status: 200, body: SOURCE },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition" });
    expect(await screen.findByText("No data source on this branch.")).toBeInTheDocument();

    fireEvent.click(screen.getByText("New source"));
    fill("Label", "CRM");
    expect(screen.getByLabelText("Name")).toHaveValue("crm");
    await screen.findByRole("option", { name: "sites (shared/site)" });
    fill("Storage fed", "sites");
    // L'ordre posé par Gael : le storage, puis le modèle source, puis la chaîne.
    await screen.findByRole("option", { name: "pudo/import-crm" });
    fill("Source model", "pudo/import-crm");
    await screen.findByRole("option", { name: "Import des comptes (comptes-import)" });
    fill("Transformation chain", "comptes-import");
    fill("Split path", "$.accounts[*]");
    fireEvent.click(screen.getByLabelText("Large file mode (streamed parsing)"));
    fireEvent.click(screen.getByText("Declare the source"));

    expect(await screen.findByText("sources/crm.yaml")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${ROUTE}${Q}`)?.body).toEqual(SOURCE);
  });

  it("no longer offers the model, the key or the filterables: they moved to the storage", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition" });
    fireEvent.click(await screen.findByText("New source"));

    expect(screen.queryByLabelText("Target model")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Key rules")).not.toBeInTheDocument();
    expect(screen.queryByText("Add a filterable property")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Storage fed")).toBeInTheDocument();
    expect(screen.getByLabelText("Source model")).toBeInTheDocument();
    // Le découpage ne sert qu'au mode gros fichier : il n'est plus obligatoire.
    expect(screen.getByLabelText("Split path")).not.toBeRequired();
  });

  it("shows every refusal with the path it concerns", async () => {
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
              { path: "chaine", code: "chaine_inconnue", detail: "absente" },
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
    expect(within(alert).getByText("storage")).toBeInTheDocument();
    expect(alert).toHaveTextContent("Storage “absent” does not exist on this branch.");
    expect(alert).toHaveTextContent("Chain “absente” does not exist on this branch.");
  });

  it("opens a source from its whole row, with no Open button", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}${Q}`]: {
        status: 200,
        body: [{ name: "crm", label: "CRM", storage: "sites", chain: "comptes-import" }],
      },
      [`GET ${ROUTE}/crm${Q}`]: { status: 200, body: SOURCE },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition" });

    expect(await screen.findByText("sources/crm.yaml")).toBeInTheDocument();
    expect(screen.queryByText("Open")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "CRM" }));

    expect(await screen.findByLabelText("Split path")).toBeInTheDocument();
  });

  it("refuses a name already taken by a different source", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`POST ${ROUTE}${Q}`]: { status: 409, body: { detail: "nom_pris" } },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition" });
    fireEvent.click(await screen.findByText("New source"));
    fireEvent.submit(screen.getByRole("form", { name: "Declare the source" }));

    expect(
      await screen.findByText("A different source already has this name on the branch."),
    ).toBeInTheDocument();
  });
});

describe("SourceScreen", () => {
  it("keeps the name frozen and announces the rewrite a change will cause", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}/crm${Q}`]: { status: 200, body: SOURCE },
      [`PUT ${ROUTE}/crm${Q}`]: {
        status: 200,
        body: { ...SOURCE, large_file: false, rewrite_announced: true },
      },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition", source: "crm" });
    expect(await screen.findByLabelText("Name")).toBeDisabled();
    expect(screen.getByLabelText("Split path")).toHaveValue("$.accounts[*]");

    fireEvent.click(screen.getByLabelText("Large file mode (streamed parsing)"));
    fireEvent.click(screen.getByText("Save the source"));

    expect(await screen.findByText(/the next import will rewrite every object/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === `PUT ${ROUTE}/crm${Q}`)?.body).toEqual({
      ...SOURCE,
      large_file: false,
    });
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
