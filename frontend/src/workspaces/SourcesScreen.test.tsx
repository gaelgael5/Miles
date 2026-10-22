import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "work/atelier" };
const ROUTE = "/api/workspaces/retrait/sources";
const Q = "?branch=edition";
const SOURCE = {
  name: "comptes",
  model: "shared/compte",
  split: "$.accounts[*]",
  keys: ["$.accountId", "$.region"],
  chain: "comptes-import",
  large_file: true,
  unified_transaction: false,
  filterables: [{ name: "code", jpath: "$.code" }],
};
const PICKERS = {
  [`GET /api/workspaces/retrait/data-models${Q}`]: {
    status: 200,
    body: [{ scope: "shared", name: "compte", path: "data-models/shared/compte.yaml" }],
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
  it("declares a source with its model, chain, keys and filterables, then opens it", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`POST ${ROUTE}${Q}`]: { status: 201, body: { ...SOURCE, rewrite_announced: false } },
      [`GET ${ROUTE}/comptes${Q}`]: { status: 200, body: SOURCE },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition" });
    expect(await screen.findByText("No data source on this branch.")).toBeInTheDocument();

    fireEvent.click(screen.getByText("New source"));
    fill("Name", "comptes");
    await screen.findByRole("option", { name: "shared/compte" });
    fill("Target model", "shared/compte");
    fill("Split path", "$.accounts[*]");
    fill("Key rules", "$.accountId\n\n  $.region  ");
    await screen.findByRole("option", { name: "Import des comptes (comptes-import)" });
    fill("Transformation chain", "comptes-import");
    fireEvent.click(screen.getByLabelText("Large file mode (streamed parsing)"));
    fireEvent.click(screen.getByText("Add a filterable property"));
    fill("Name 1", "code");
    fill("Path 1", "$.code");
    fireEvent.click(screen.getByText("Declare the source"));

    expect(await screen.findByText("sources/comptes.yaml")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${ROUTE}${Q}`)?.body).toEqual(SOURCE);
  });

  it("shows every refusal with the path it concerns", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`POST ${ROUTE}${Q}`]: {
        status: 422,
        body: {
          detail: {
            code: "source_invalide",
            problems: [
              { path: "filtrables[0].jpath", code: "tableau_interdit", detail: "$.enseignes" },
              { path: "chaine", code: "chaine_inconnue", detail: "absente" },
            ],
          },
        },
      },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition" });
    fireEvent.click(await screen.findByText("New source"));
    fill("Name", "comptes");
    fireEvent.submit(screen.getByRole("form", { name: "Declare the source" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("filtrables[0].jpath")).toBeInTheDocument();
    expect(alert).toHaveTextContent("“$.enseignes” designates an array");
    expect(alert).toHaveTextContent("Chain “absente” does not exist on this branch.");
  });

  it("refuses a name already taken by a different source", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`POST ${ROUTE}${Q}`]: { status: 409, body: { detail: "nom_pris" } },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition" });
    fireEvent.click(await screen.findByText("New source"));
    fireEvent.submit(screen.getByRole("form", { name: "Declare the source" }));

    expect(await screen.findByText("A different source already has this name on the branch.")).toBeInTheDocument();
  });
});

describe("SourceScreen", () => {
  it("keeps the name frozen and announces the rewrite a change will cause", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}/comptes${Q}`]: { status: 200, body: SOURCE },
      [`PUT ${ROUTE}/comptes${Q}`]: {
        status: 200,
        body: { ...SOURCE, filterables: [], rewrite_announced: true },
      },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition", source: "comptes" });
    expect(await screen.findByLabelText("Name")).toBeDisabled();
    expect(screen.getByLabelText("Key rules")).toHaveValue("$.accountId\n$.region");

    fireEvent.click(screen.getByText("Remove filterable 1"));
    fireEvent.click(screen.getByText("Save the source"));

    expect(await screen.findByText(/the next import will rewrite every object/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === `PUT ${ROUTE}/comptes${Q}`)?.body).toEqual({ ...SOURCE, filterables: [] });
  });

  it("deletes the source after confirmation and returns to the list", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...PICKERS,
      [`GET ${ROUTE}/comptes${Q}`]: { status: 200, body: SOURCE },
      [`DELETE ${ROUTE}/comptes${Q}`]: { status: 204 },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition", source: "comptes" });
    fireEvent.click(await screen.findByText("Delete the source"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Delete the source"));

    expect(await screen.findByText("No data source on this branch.")).toBeInTheDocument();
    expect(calls.some((c) => c.key === `DELETE ${ROUTE}/comptes${Q}`)).toBe(true);
  });
});
