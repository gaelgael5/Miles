import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, renderWorkspaces } from "./workspaceFixtures";

// L'utilité des champs, deuxième onglet d'un modèle (Gael, 05/11/2026).
const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/data-models";
const MODEL = {
  scope: "shared",
  name: "personne",
  path: "shared/messages/personne.yaml",
  label: "Personne",
  version: 3,
};
const YAML =
  "$schema: https://json-schema.org/draft/2020-12/schema\n$id: miles:/shared/personne\n" +
  "title: Personne\ntype: object\nproperties:\n  Id:\n    type: string\n" +
  "  Nom:\n    type: string\n  Adresse:\n    type: object\n    properties:\n      Ville:\n        type: string\n";

afterEach(() => {
  vi.unstubAllGlobals();
});

function open(content = YAML, branch = "edition") {
  const calls = mockApi({
    ...HELD,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    [`GET ${ROUTE}/shared/personne`]: { status: 200, body: { ...MODEL, content } },
    [`GET ${ROUTE}`]: { status: 200, body: [MODEL] },
    [`PUT ${ROUTE}/shared/personne`]: {
      status: 200,
      body: { ...MODEL, content, version: 4 },
    },
  } as Parameters<typeof mockApi>[0]);
  renderWorkspaces({ id: "retrait", view: "dataModels", branch, model: "shared/personne" });
  return calls;
}

async function openUsage(content = YAML, branch = "edition") {
  const calls = open(content, branch);
  // Premier chargement de JSONJoy dans le fichier : plus lent que les suivants.
  await screen.findByLabelText("YAML", {}, { timeout: 10_000 });
  fireEvent.click(screen.getByRole("tab", { name: "Field usage" }));
  return calls;
}

describe("field usage", () => {
  it("lists the top-level fields only, and does not let them be changed", async () => {
    // La liste est celle du modèle : un ajout de champ ici aurait été un deuxième
    // endroit où le décrire, et les deux auraient divergé.
    await openUsage();

    const table = within(screen.getByRole("region", { name: "Field usage" }));
    expect(table.getByText("Id")).toBeInTheDocument();
    expect(table.getByText("Nom")).toBeInTheDocument();
    expect(table.getByText("Adresse")).toBeInTheDocument();
    // « Ville » est sous « Adresse » : elle se coche sur la page d'un storage.
    expect(table.queryByText("Ville")).toBeNull();
    expect(table.queryByRole("textbox")).toBeNull();
  });

  it("offers no box on a field that is not a single value, and says why", async () => {
    await openUsage();

    expect(screen.queryByLabelText("Adresse is part of the functional key")).toBeNull();
    expect(screen.getAllByText("not a single value").length).toBe(2);
  });

  it("writes the usage into the model, where the YAML shows it", async () => {
    // Par le même canal que l'éditeur : l'utilité est DANS le schéma, donc « Enregistrer »
    // la porte, et rien ne part au serveur avant.
    await openUsage();

    fireEvent.click(screen.getByLabelText("Id is part of the functional key"));
    fireEvent.click(screen.getByLabelText("Nom shows in the table"));
    fireEvent.click(screen.getByRole("tab", { name: "Editor" }));

    const yaml = (await screen.findByLabelText("YAML")) as HTMLTextAreaElement;
    expect(yaml.value).toContain("x-miles:");
    expect(yaml.value).toContain("- $.Id");
    expect(yaml.value).toContain("- $.Nom");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("reads back what the model already declares", async () => {
    await openUsage(`${YAML}x-miles:\n  key:\n    - $.Id\n  columns:\n    - $.Nom\n`);

    expect(screen.getByLabelText("Id is part of the functional key")).toBeChecked();
    expect(screen.getByLabelText("Nom shows in the table")).toBeChecked();
    expect(screen.getByLabelText("Id shows in the table")).not.toBeChecked();
  });

  it("sends the usage with the model when saving", async () => {
    const calls = await openUsage();

    fireEvent.click(screen.getByLabelText("Id is part of the functional key"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(calls.some((call) => call.key.startsWith("PUT"))).toBe(true));
    const put = calls.find((call) => call.key.startsWith("PUT"));
    expect(JSON.stringify(put?.body)).toContain("$.Id");
  });

  it("lets the root branch be read, never changed", async () => {
    // La racine est en lecture seule (story dca0eb0e) : les cases s'y lisent, cochées
    // ou non, et ne s'y touchent pas. Sans la garde, l'écran laisserait cocher une case
    // dont l'enregistrement serait refusé, loin du geste.
    open(YAML, "atelier");
    fireEvent.click(await screen.findByRole("tab", { name: "Field usage" }, { timeout: 10_000 }));

    expect(screen.getByLabelText("Id is part of the functional key")).toBeDisabled();
    expect(screen.getByLabelText("Nom shows in the table")).toBeDisabled();
  }, 15_000);

  it("says nothing can be declared while the YAML does not read", async () => {
    await openUsage();
    fireEvent.click(screen.getByRole("tab", { name: "Editor" }));
    const yaml = await screen.findByLabelText("YAML");

    fireEvent.change(yaml, { target: { value: "type: object\nproperties: [\n" } });
    fireEvent.click(screen.getByRole("tab", { name: "Field usage" }));

    expect(screen.getByRole("note")).toHaveTextContent("The YAML cannot be read");
  });
});
