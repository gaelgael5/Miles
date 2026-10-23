import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

// Arbre à gauche, YAML à droite, en mémoire jusqu'à « Enregistrer » (story 7208ba06).
const WORKING = { ...CONFIGURED, work_branch: "work/atelier" };
const ROUTE = "/api/workspaces/retrait/data-models";
const MODEL = { scope: "shared", name: "personne", path: "shared/messages/personne.yaml", label: "Personne" };
const ADRESSE = { scope: "shared", name: "adresse", path: "shared/messages/adresse.yaml", label: null };
const YAML = "nom: personne\nversion: 1\nproprietes:\n  nom:\n    type: chaine\n";

afterEach(() => {
  vi.unstubAllGlobals();
});

function open(extra: Record<string, unknown> = {}) {
  const calls = mockApi({
    ...HELD,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    [`GET ${ROUTE}/shared/personne?branch=edition`]: { status: 200, body: { ...MODEL, content: YAML } },
    [`GET ${ROUTE}?branch=edition`]: { status: 200, body: [MODEL, ADRESSE] },
    ...extra,
  } as Parameters<typeof mockApi>[0]);
  renderWorkspaces({ id: "retrait", view: "dataModels", branch: "edition", model: "shared/personne" });
  return calls;
}

async function tree() {
  return within(await screen.findByRole("group", { name: "Properties" }));
}

describe("model tree", () => {
  it("shows the properties and rewrites the YAML as they are edited, in memory only", async () => {
    const calls = open();
    const t = await tree();
    expect(t.getByLabelText("Name")).toHaveValue("nom");

    fireEvent.click(t.getByRole("button", { name: "Add a property" }));
    const names = t.getAllByLabelText("Name");
    fireEvent.change(names[1] as HTMLElement, { target: { value: "statut" } });
    const types = t.getAllByLabelText("Type");
    fireEvent.change(types[1] as HTMLElement, { target: { value: "enumeration" } });
    fireEvent.change(t.getByLabelText("Values (comma-separated)"), { target: { value: "ouvert, clos" } });
    fireEvent.click(t.getAllByLabelText("Required")[1] as HTMLElement);

    expect(screen.getByLabelText("Model (YAML)")).toHaveValue(
      YAML + "  statut:\n    type: enumeration\n    valeurs:\n      - ouvert\n      - clos\n    obligatoire: true\n",
    );
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(calls.some((c) => c.key.startsWith("PUT"))).toBe(false);
  });

  it("offers the visible models for an object, and lists one level deeper for a list", async () => {
    open();
    const t = await tree();

    fireEvent.change(t.getByLabelText("Type"), { target: { value: "objet" } });
    fireEvent.change(t.getByLabelText("Referenced model"), { target: { value: "adresse" } });
    expect(screen.getByLabelText("Model (YAML)")).toHaveValue(
      "nom: personne\nversion: 1\nproprietes:\n  nom:\n    type: objet\n    modele: adresse\n",
    );
    fireEvent.change(t.getByLabelText("Type"), { target: { value: "liste" } });
    expect(t.getAllByLabelText("Type")).toHaveLength(2);
  });

  it("refuses a duplicate name without losing the other property", async () => {
    open();
    const t = await tree();
    fireEvent.click(t.getByRole("button", { name: "Add a property" }));

    fireEvent.change(t.getAllByLabelText("Name")[1] as HTMLElement, { target: { value: "nom" } });

    expect(t.getByRole("alert")).toHaveTextContent("Another property already has this name.");
    expect(screen.getByLabelText("Model (YAML)")).toHaveValue(
      YAML + "  propriete_1:\n    type: chaine\n",
    );
  });

  it("follows the YAML, and greys the tree out where the YAML is unreadable", async () => {
    open();
    await tree();

    fill("Model (YAML)", "nom: personne\nversion: 1\nproprietes:\n  age:\n    type: entier\n");
    expect((await tree()).getByLabelText("Name")).toHaveValue("age");
    fill("Model (YAML)", "nom: personne\nproprietes:\n  a: [chaine\n");

    expect(screen.queryByRole("group", { name: "Properties" })).toBeNull();
    expect(screen.getByRole("note")).toHaveTextContent("Unreadable YAML, line");
  });

  it("saves what the tree produced, and asks before leaving unsaved work", async () => {
    const calls = open({ [`PUT ${ROUTE}/shared/personne?branch=edition`]: { status: 200, body: MODEL } });
    const t = await tree();
    fireEvent.change(t.getByLabelText("Type"), { target: { value: "entier" } });

    fireEvent.click(screen.getByRole("button", { name: "← Back to models" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("they will be lost");
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await vi.waitFor(() =>
      expect(calls.find((c) => c.key.startsWith("PUT"))?.body).toEqual({
        content: "nom: personne\nversion: 1\nproprietes:\n  nom:\n    type: entier\n",
      }),
    );
  });
});
