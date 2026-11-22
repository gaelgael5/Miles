import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, modelListing, renderWorkspaces } from "./workspaceFixtures";

/**
 * À quoi sert chaque modèle (story e36192f8). Gael, le 16/11/2026 : « sur les models
 * (event et objets), la façon d'identifier qui fait quoi m'échappe. »
 *
 * Les doublures sont DISCRIMINANTES : deux modèles de même emplacement, l'un payload d'un
 * type d'event ET stocké par un storage, l'autre que rien ne désigne. Avant le 14/11/2026
 * le dossier les séparait ; ces deux lignes-ci sont exactement celles que plus rien ne
 * distinguait.
 */
const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/data-models";
const NO_VERSION = {
  "GET /api/workspaces/retrait/versions?branch=edition": { status: 200, body: [] },
};
const COLIS = {
  scope: "shared",
  name: "colis",
  path: "shared/models/colis.yaml",
  label: "Colis",
  version: 2,
  usages: [
    {
      kind: "event_type",
      name: "colis_recu",
      label: "Colis reçu",
      path: "shared/shared.wf",
      part: null,
    },
    { kind: "storage", name: "sites", label: "Sites", path: "storages/sites.yaml", part: null },
  ],
};
/**
 * Désigné deux fois, et par AUCUN type d'event : c'est lui qui éprouve le résumé de la
 * ligne depuis le 22/11/2026, parce qu'un payload n'est plus dans cette liste du tout
 * (story 7b4f7a32). Deux natures, donc, comme avant — mais deux natures qui restent.
 */
const SUIVI = {
  scope: "shared",
  name: "suivi",
  path: "shared/models/suivi.yaml",
  label: "Suivi",
  version: 3,
  usages: [
    { kind: "storage", name: "sites", label: "Sites", path: "storages/sites.yaml", part: null },
    {
      kind: "chain_step",
      name: "import-colis",
      label: "Import",
      path: "chains/import-colis/chain.yaml",
      part: "vers-pivot",
    },
  ],
};
const ORPHELIN = {
  scope: "shared",
  name: "orphelin",
  path: "shared/models/orphelin.yaml",
  label: "Orphelin",
  version: 1,
  usages: [],
};
const CASSEE = {
  kind: "storage",
  name: "comptes",
  label: "Comptes",
  path: "storages/comptes.yaml",
  part: null,
  target: "shared/absent",
};
const YAML =
  "$schema: https://json-schema.org/draft/2020-12/schema\n$id: miles:/shared/colis\n" +
  "title: Colis\ntype: object\nproperties:\n  Id:\n    type: string\n";

afterEach(() => {
  vi.unstubAllGlobals();
});

function listed(models: object[], broken: object[] = []) {
  return mockApi({
    ...HELD,
    ...NO_VERSION,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    [`GET ${ROUTE}?branch=edition`]: { status: 200, body: modelListing(models, broken) },
    [`GET ${ROUTE}/shared/colis?branch=edition`]: {
      status: 200,
      body: { ...COLIS, content: YAML },
    },
    [`GET ${ROUTE}/shared/orphelin?branch=edition`]: {
      status: 200,
      body: { ...ORPHELIN, content: YAML.replace("colis", "orphelin") },
    },
    "GET /api/workspaces/retrait/domains?branch=edition": { status: 200, body: [] },
    "GET /api/workspaces/retrait/storages/sites?branch=edition": { status: 404, body: null },
  } as Parameters<typeof mockApi>[0]);
}

async function openRole(models: object[] = [COLIS, ORPHELIN], broken: object[] = []) {
  const calls = listed(models, broken);
  renderWorkspaces({ id: "retrait", view: "dataModels", branch: "edition", model: "shared/colis" });
  // Premier chargement de JSONJoy dans le fichier : plus lent que les suivants.
  await screen.findByLabelText("YAML", {}, { timeout: 10_000 });
  fireEvent.click(screen.getByRole("tab", { name: "Used by (2)" }));
  return calls;
}

describe("what designates a model", () => {
  it("says on each row what the model serves, and says when nothing does", async () => {
    listed([SUIVI, ORPHELIN]);
    renderWorkspaces({ id: "retrait", view: "dataModels", branch: "edition" });

    const row = (await screen.findByText("Suivi")).closest("li") as HTMLElement;
    expect(within(row).getByText("1 storage · 1 chain step")).toBeInTheDocument();
    const alone = (screen.getByText("Orphelin")).closest("li") as HTMLElement;
    expect(within(alone).getByText("Nothing designates it")).toBeInTheDocument();
  });

  it("leaves the payload of an event type out of the list, and keeps the others", async () => {
    // Gael, le 19/11/2026 : « les events apparaissent dans le menu events mais pas dans
    // le menu model. » C'est l'USAGE qui l'écarte : `COLIS` et `SUIVI` sont au même
    // endroit, du même nom de rubrique, et seul le premier est un payload.
    listed([COLIS, SUIVI, ORPHELIN]);
    renderWorkspaces({ id: "retrait", view: "dataModels", branch: "edition" });

    await screen.findByText("Suivi");
    expect(screen.getByText("Orphelin")).toBeInTheDocument();
    expect(screen.queryByText("Colis")).not.toBeInTheDocument();
  });

  it("shows the declarations whose target the branch does not have, and what they name", async () => {
    // Critère 5 : la référence cassée se voit ici, au lieu de n'apparaître qu'au blocage
    // d'une version. Elle ne tient à aucune ligne, d'où le bloc en tête.
    listed([COLIS, ORPHELIN], [CASSEE]);
    renderWorkspaces({ id: "retrait", view: "dataModels", branch: "edition" });

    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("Storage “comptes” designates shared/absent");
    expect(note).toHaveTextContent("storages/comptes.yaml");
  });

  it("names each designator on the model's own screen, the event type included", async () => {
    // Critère 3 : c'est le TYPE d'event qu'on cherche, pas l'artefact du périmètre.
    await openRole();

    const region = within(screen.getByRole("region", { name: "What designates this model" }));
    expect(region.getByText("Colis reçu")).toBeInTheDocument();
    expect(region.getByText(/colis_recu · shared\/shared\.wf/)).toBeInTheDocument();
    expect(region.getByText("Sites")).toBeInTheDocument();
  });

  it("opens the storage that designates the model", async () => {
    const calls = await openRole();

    const region = within(screen.getByRole("region", { name: "What designates this model" }));
    fireEvent.click(region.getByRole("button", { name: "Sites" }));

    await waitFor(() =>
      expect(calls.some((call) => call.key.includes("/storages/sites"))).toBe(true),
    );
  });

  it("says plainly that nothing designates a model, without calling it a fault", async () => {
    listed([COLIS, ORPHELIN]);
    renderWorkspaces({
      id: "retrait",
      view: "dataModels",
      branch: "edition",
      model: "shared/orphelin",
    });
    await screen.findByLabelText("YAML", {}, { timeout: 10_000 });

    fireEvent.click(screen.getByRole("tab", { name: "Used by (0)" }));

    expect(screen.getByRole("region", { name: "What designates this model" })).toHaveTextContent(
      "No declaration designates this model",
    );
  }, 15_000);
});
