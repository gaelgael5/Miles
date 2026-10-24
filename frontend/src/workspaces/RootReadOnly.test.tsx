import { screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import type { WorkspaceSelection } from "../layout/WorkspacesNav";
import { CONFIGURED, renderWorkspaces } from "./workspaceFixtures";

// La racine est en lecture seule (story dca0eb0e) : on la lit, on y fige une version,
// mais l'écran n'y offre aucun bouton qui en changerait le contenu.
const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const WS = "/api/workspaces/retrait";
const Q = "?branch=atelier";
const NOTICE = /This is the workspace root branch: it is read-only/;
const MODEL = { scope: "shared", name: "personne", path: "shared/messages/personne.yaml" };
const CHAIN = {
  slug: "import",
  label: "Import",
  steps: [
    { name: "copier", template: "{ }", target: null, source_model: null, destination_model: null },
  ],
};
const SOURCE = {
  name: "comptes",
  label: "Comptes",
  storage: "personnes",
  split: "$.accounts[*]",
  chain: "import",
  large_file: false,
  unified_transaction: false,
};
const STORAGE = {
  name: "personnes",
  label: "Personnes",
  model: "shared/personne",
  keys: ["$.id"],
  indexables: [{ name: "code", jpath: "$.code" }],
};
const VERSION = { number: 1, label: "Racine", commit: "0123456789abcdef", author: "admin", saved_at: "2026-10-22T10:00:00Z" };

afterEach(() => {
  vi.unstubAllGlobals();
});

function onRoot(selection: Omit<NonNullable<WorkspaceSelection>, "id" | "branch">) {
  mockApi({
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    "GET /api/workspaces/retrait/branches": {
      status: 200,
      body: [{ slug: "atelier", label: "atelier", branch: "back/retrait/atelier", base: true }],
    },
    [`GET ${WS}/data-models${Q}`]: { status: 200, body: [MODEL] },
    [`GET ${WS}/versions${Q}`]: { status: 200, body: [VERSION] },
    [`GET ${WS}/contracts${Q}`]: { status: 200, body: [] },
    [`GET ${WS}/contracts/suivi${Q}`]: {
      status: 200,
      body: { slug: "suivi", label: "Suivi", sens: "externe", versions: [] },
    },
    [`GET ${WS}/transformations${Q}`]: { status: 200, body: [{ slug: "import", label: "Import", steps: 1 }] },
    [`GET ${WS}/transformations/import${Q}`]: { status: 200, body: CHAIN },
    [`GET ${WS}/transformations/import/sample${Q}`]: { status: 200, body: { sample: null } },
    [`GET ${WS}/sources${Q}`]: { status: 200, body: [] },
    [`GET ${WS}/sources/comptes${Q}`]: { status: 200, body: SOURCE },
    [`GET ${WS}/storages${Q}`]: { status: 200, body: [] },
    [`GET ${WS}/storages/personnes${Q}`]: { status: 200, body: STORAGE },
    [`GET ${WS}/data-models/shared/personne/paths${Q}`]: {
      status: 200,
      body: { paths: [{ path: "$.id", type: "string", description: "" }] },
    },
  });
  renderWorkspaces({ id: "retrait", branch: "atelier", ...selection });
}

describe("root branch", () => {
  it("lists the models without offering to add or delete one", async () => {
    onRoot({ view: "dataModels" });
    expect(await screen.findByText("personne")).toBeInTheDocument();
    expect(screen.getByText(NOTICE)).toBeInTheDocument();
    expect(screen.queryByText("Add a model")).toBeNull();
    expect(screen.queryByText("Delete")).toBeNull();
  });

  it("can still be frozen as a version, but not restored", async () => {
    onRoot({ view: "branch" });
    expect(await screen.findByText(/Racine/)).toBeInTheDocument();
    expect(screen.getByText("Save a version")).toBeInTheDocument();
    expect(screen.queryByText("Return to this version")).toBeNull();
  });

  it("does not offer to declare a contract", async () => {
    onRoot({ view: "contracts" });
    expect(await screen.findByText(NOTICE)).toBeInTheDocument();
    expect(screen.queryByText("Declare a contract")).toBeNull();
  });

  it("shows a contract without the form to integrate a file", async () => {
    onRoot({ view: "contracts", contract: "suivi" });
    expect(await screen.findByRole("heading", { name: "Suivi" })).toBeInTheDocument();
    expect(screen.queryByText("Integrate a file")).toBeNull();
  });

  it("does not offer to create a chain", async () => {
    onRoot({ view: "transformations" });
    expect(await screen.findByText("Import")).toBeInTheDocument();
    expect(screen.queryByText("New chain")).toBeNull();
  });

  it("shows a chain to read and try, without saving, deleting or moving steps", async () => {
    onRoot({ view: "transformations", chain: "import" });
    expect(await screen.findByText("Run")).toBeInTheDocument();
    for (const label of ["Save the chain", "Delete the chain", "Add a step", "Move up", "Remove"]) {
      expect(screen.queryByText(label)).toBeNull();
    }
    // Le template a quitté cet écran (24/10/2026) : ce qu'on y vérifie désormais, c'est
    // que le choix des modèles d'une étape y est fermé.
    expect(screen.getByLabelText("Source model")).toBeDisabled();
  });

  it("does not offer to declare a source", async () => {
    onRoot({ view: "sources" });
    expect(await screen.findByText(NOTICE)).toBeInTheDocument();
    expect(screen.queryByText("New source")).toBeNull();
  });

  it("shows a source with every field disabled and no save or delete", async () => {
    onRoot({ view: "sources", source: "comptes" });
    expect(await screen.findByLabelText("Split path")).toBeInTheDocument();
    for (const label of ["Save the source", "Delete the source"]) {
      expect(screen.queryByText(label)).toBeNull();
    }
    expect(screen.getByLabelText("Split path")).toBeDisabled();
  });

  // Critère 19 de 844f15ad : la racine se lit, elle ne se modifie pas.
  it("does not offer to declare a storage", async () => {
    onRoot({ view: "storages" });
    expect(await screen.findByText(NOTICE)).toBeInTheDocument();
    expect(screen.queryByText("New storage")).toBeNull();
  });

  it("shows a storage with every field disabled and no save or delete", async () => {
    onRoot({ view: "storages", storage: "personnes" });
    expect(await screen.findByLabelText("Object model")).toBeDisabled();
    for (const label of ["Save the storage", "Delete the storage"]) {
      expect(screen.queryByText(label)).toBeNull();
    }
    // L'arbre se lit, il ne se coche pas : la racine ne se modifie jamais.
    const [keyTree] = await screen.findAllByRole("list", { name: "Model properties" });
    for (const box of within(keyTree as HTMLElement).getAllByRole("checkbox")) {
      expect(box).toBeDisabled();
    }
  });
});
