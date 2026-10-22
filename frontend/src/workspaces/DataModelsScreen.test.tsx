import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { BARE, CONFIGURED, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "work/atelier" };
const ROUTE = "/api/workspaces/retrait/data-models";
const NO_VERSION = { "GET /api/workspaces/retrait/versions?branch=atelier": { status: 200, body: [] } };
const PERSONNE = { scope: "shared", name: "personne", path: "shared/messages/personne.yaml" };
const COLIS = { scope: "suivi", name: "colis", path: "domains/suivi/messages/colis.yaml" };
const YAML = "nom: personne\nversion: 1\nproprietes:\n  nom:\n    type: chaine\n";

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openModels() {
  renderWorkspaces();
  fireEvent.click(await screen.findByText("Data models"));
  return screen.findByRole("heading", { name: "Data models — Retrait de colis" });
}

describe("DataModelsScreen", () => {
  it("is offered only once the workspace has a work branch", async () => {
    mockApi({ "GET /api/workspaces": { status: 200, body: [{ ...BARE, id: "nu" }, WORKING] } });
    renderWorkspaces();

    expect(await screen.findAllByText("Data models")).toHaveLength(1);
  });

  it("lists the models of the work branch and shows one exactly as stored", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...NO_VERSION,
      [`GET ${ROUTE}?branch=atelier`]: { status: 200, body: [COLIS, PERSONNE] },
      [`GET ${ROUTE}/shared/personne?branch=atelier`]: { status: 200, body: { ...PERSONNE, content: YAML } },
    });
    await openModels();

    expect(await screen.findByText("domains/suivi/messages/colis.yaml")).toBeInTheDocument();
    const row = screen.getByText("personne").closest("li") as HTMLElement;
    expect(within(row).getByText("Shared")).toBeInTheDocument();
    fireEvent.click(within(row).getByText("Show"));

    expect(await within(row).findByLabelText(PERSONNE.path)).toHaveTextContent(
      "nom: personne version: 1",
    );
    expect(within(row).getByLabelText(PERSONNE.path).textContent).toBe(YAML);
  });

  it("writes a shared model when no domain is given", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...NO_VERSION,
      [`GET ${ROUTE}?branch=atelier`]: [
        { status: 200, body: [] },
        { status: 200, body: [PERSONNE] },
      ],
      [`POST ${ROUTE}?branch=atelier`]: { status: 201, body: PERSONNE },
    });
    await openModels();
    fireEvent.click(screen.getByText("Add a model"));
    fill("Model (YAML)", YAML);

    fireEvent.click(screen.getByText("Write to the work branch"));

    expect(await screen.findByText("shared/messages/personne.yaml")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${ROUTE}?branch=atelier`)?.body).toEqual({
      scope: "shared",
      content: YAML,
    });
  });

  it("lists every grammar problem with its place in the document", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...NO_VERSION,
      [`GET ${ROUTE}?branch=atelier`]: { status: 200, body: [] },
      [`POST ${ROUTE}?branch=atelier`]: {
        status: 422,
        body: {
          detail: {
            code: "modele_non_conforme",
            problems: [
              { path: "proprietes.b.type", code: "type_inconnu", detail: "texte" },
              { path: "proprietes.d.modele", code: "modele_inconnu", detail: "personne" },
            ],
          },
        },
      },
    });
    await openModels();
    fireEvent.click(screen.getByText("Add a model"));
    fill("Domain", "suivi");
    fill("Model (YAML)", "nom: x");
    fireEvent.click(screen.getByText("Write to the work branch"));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The model does not follow the grammar:");
    expect(alert).toHaveTextContent("proprietes.b.type — unknown type “texte”");
    expect(alert).toHaveTextContent("proprietes.d.modele — model “personne” does not exist");
  });

  it("names the YAML position and the models that still use one being deleted", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...NO_VERSION,
      [`GET ${ROUTE}?branch=atelier`]: { status: 200, body: [PERSONNE] },
      [`POST ${ROUTE}?branch=atelier`]: {
        status: 422,
        body: { detail: { code: "yaml_invalide", line: 3, column: 7, message: "bad" } },
      },
      [`DELETE ${ROUTE}/shared/personne?branch=atelier`]: {
        status: 409,
        body: { detail: { code: "utilise", by: [COLIS.path] } },
      },
    });
    await openModels();
    fireEvent.click(screen.getByText("Add a model"));
    fill("Model (YAML)", "nom: [");
    fireEvent.click(screen.getByText("Write to the work branch"));
    expect(await screen.findByText("Invalid YAML, line 3, column 7: bad")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Delete"));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));

    expect(
      await screen.findByText(`Other models use this one: ${COLIS.path}.`),
    ).toBeInTheDocument();
  });
});
