import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { BARE, CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "work/atelier" };
const ROUTE = "/api/workspaces/retrait/data-models";
const NO_VERSION = { "GET /api/workspaces/retrait/versions?branch=edition": { status: 200, body: [] } };
const PERSONNE = {
  scope: "shared",
  name: "personne",
  path: "shared/messages/personne.yaml",
  label: "Personne livrée",
};
const COLIS = { scope: "suivi", name: "colis", path: "domains/suivi/messages/colis.yaml", label: null };
const DRAFT = "nom: personne\nversion: 1\nproprietes: {}\n";
const YAML = "nom: personne\nversion: 1\nproprietes:\n  nom:\n    type: chaine\n";

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openModels() {
  // Une branche enfant : la racine est en lecture seule (story dca0eb0e).
  renderWorkspaces({ id: "retrait", view: "dataModels", branch: "edition" });
  return screen.findByRole("heading", { name: "Data models — Retrait de colis" });
}

describe("DataModelsScreen", () => {
  it("is offered only once the workspace has a work branch", async () => {
    mockApi({ "GET /api/workspaces": { status: 200, body: [{ ...BARE, id: "nu" }, WORKING] } });
    renderWorkspaces();

    expect(await screen.findAllByText("Data models")).toHaveLength(1);
  });

  it("lists the models by label, and opens one on its YAML exactly as stored", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...NO_VERSION,
      [`GET ${ROUTE}?branch=edition`]: { status: 200, body: [COLIS, PERSONNE] },
      [`GET ${ROUTE}/shared/personne?branch=edition`]: { status: 200, body: { ...PERSONNE, content: YAML } },
    });
    await openModels();

    expect(await screen.findByText("domains/suivi/messages/colis.yaml")).toBeInTheDocument();
    // Sans label (créé par son YAML), le modèle se nomme par son nom.
    expect(screen.getByText("colis")).toBeInTheDocument();
    const row = screen.getByText("Personne livrée").closest("li") as HTMLElement;
    expect(within(row).getByText("Shared")).toBeInTheDocument();
    fireEvent.click(within(row).getByText("Open"));

    expect(await screen.findByRole("heading", { name: "Personne livrée" })).toBeInTheDocument();
    expect(await screen.findByLabelText("YAML", {}, { timeout: 10_000 })).toHaveValue(YAML);
  });

  it("creates a model by label and slug, then opens it to write its YAML", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...NO_VERSION,
      [`GET ${ROUTE}?branch=edition`]: { status: 200, body: [] },
      [`POST ${ROUTE}/declarations?branch=edition`]: { status: 201, body: PERSONNE },
      [`GET ${ROUTE}/shared/personne?branch=edition`]: [
        { status: 200, body: { ...PERSONNE, content: DRAFT } },
        { status: 200, body: { ...PERSONNE, content: YAML } },
      ],
      [`PUT ${ROUTE}/shared/personne?branch=edition`]: { status: 200, body: PERSONNE },
    });
    await openModels();
    fireEvent.click(await screen.findByText("Add a model"));
    const form = screen.getByRole("form", { name: "New data model" });
    expect(within(form).queryByLabelText("YAML")).toBeNull();
    fill("Label", "Personne livrée");
    expect(screen.getByLabelText("Slug")).toHaveValue("personne-livree");
    fill("Slug", "personne");

    fireEvent.click(screen.getByText("Create the model"));

    expect(await screen.findByLabelText("YAML")).toHaveValue(DRAFT);
    expect(calls.find((c) => c.key === `POST ${ROUTE}/declarations?branch=edition`)?.body).toEqual({
      scope: "shared",
      label: "Personne livrée",
      slug: "personne",
    });
    fill("YAML", YAML);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Model saved");
    expect(calls.find((c) => c.key === `PUT ${ROUTE}/shared/personne?branch=edition`)?.body).toEqual({
      content: YAML,
    });
  });

  it("lists every grammar problem of the YAML with its place, and the YAML position", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...NO_VERSION,
      [`GET ${ROUTE}/shared/personne?branch=edition`]: {
        status: 200,
        body: { ...PERSONNE, content: YAML },
      },
      [`PUT ${ROUTE}/shared/personne?branch=edition`]: [
        {
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
        {
          status: 422,
          body: { detail: { code: "yaml_invalide", line: 3, column: 7, message: "bad" } },
        },
      ],
    });
    renderWorkspaces({ id: "retrait", view: "dataModels", branch: "edition", model: "shared/personne" });
    await screen.findByLabelText("YAML");
    fill("YAML", "nom: x");
    fireEvent.click(await screen.findByRole("button", { name: "Save" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The model does not follow the grammar:");
    expect(alert).toHaveTextContent("proprietes.b.type — unknown type “texte”");
    expect(alert).toHaveTextContent("proprietes.d.modele — model “personne” does not exist");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Invalid YAML, line 3, column 7: bad")).toBeInTheDocument();
  });

  it("shows the YAML read-only without the hold", async () => {
    mockApi({
      "GET /api/workspaces/retrait/holds": { status: 200, body: [] },
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/shared/personne?branch=edition`]: {
        status: 200,
        body: { ...PERSONNE, content: YAML },
      },
    });
    renderWorkspaces({ id: "retrait", view: "dataModels", branch: "edition", model: "shared/personne" });

    expect(await screen.findByLabelText("YAML")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("names the models that still use one being deleted", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...NO_VERSION,
      [`GET ${ROUTE}?branch=edition`]: { status: 200, body: [PERSONNE] },
      [`DELETE ${ROUTE}/shared/personne?branch=edition`]: {
        status: 409,
        body: { detail: { code: "utilise", by: [COLIS.path] } },
      },
    });
    await openModels();

    fireEvent.click(await screen.findByText("Delete"));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));

    expect(
      await screen.findByText(`Other models use this one: ${COLIS.path}.`),
    ).toBeInTheDocument();
  });
});
