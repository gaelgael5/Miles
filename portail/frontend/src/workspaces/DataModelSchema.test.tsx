import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, renderWorkspaces } from "./workspaceFixtures";

// Éditeur visuel JSONJoy et YAML, synchronisés, en mémoire jusqu'à « Enregistrer » (e38806f3).
const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/data-models";
const MODEL = {
  scope: "shared",
  name: "personne",
  path: "shared/messages/personne.yaml",
  label: "Personne",
  version: 3,
};
const ADRESSE = { ...MODEL, name: "adresse", path: "shared/messages/adresse.yaml", label: "Adresse", version: 1 };
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
    [`GET ${ROUTE}?branch=edition`]: { status: 200, body: [MODEL, ADRESSE] },
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
