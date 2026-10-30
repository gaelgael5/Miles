import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { type TradsContext, contextNameFrom } from "../api/trads";
import { type Routes, mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, SETTINGS, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/trads?branch=edition";
const ACCUEIL: TradsContext = {
  name: "accueil",
  label: "Écrans d'accueil",
  keys: 2,
  translated: { "en-US": 2, "fr-FR": 1 },
  obsolete: {},
};
const VIDE: TradsContext = {
  name: "vide",
  label: "Encore vide",
  keys: 0,
  translated: { "en-US": 0 },
  obsolete: {},
};
// Une culture retirée du workspace dont le dépôt garde le fichier : c'est le seul
// « obsolète » que le produit crée lui-même.
const AVEC_OBSOLETE: TradsContext = { ...ACCUEIL, obsolete: { "ar-MA": 3 } };

afterEach(() => {
  vi.unstubAllGlobals();
});

function routes(contexts: Routes[string], extra: Routes = {}) {
  return mockApi({
    ...HELD,
    ...SETTINGS,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    [`GET ${ROUTE}`]: contexts,
    ...extra,
  });
}

async function openTrads() {
  // Une branche enfant : la racine est en lecture seule (story dca0eb0e).
  renderWorkspaces({ id: "retrait", view: "trads", branch: "edition" });
  await screen.findByRole("heading", { name: "Translations" });
}

describe("contextNameFrom", () => {
  it.each([
    ["Écrans d'accueil", "ecrans-d-accueil"],
    ["  Lot_2 — v1 ", "lot_2-v1"],
    ["这是", ""],
    ["x".repeat(80), "x".repeat(63)],
  ])("proposes %j as %j", (label, name) => {
    expect(contextNameFrom(label)).toBe(name);
  });
});

describe("TradsScreen", () => {
  it("lists the contexts with their key count and coverage per workspace culture", async () => {
    routes({ status: 200, body: [ACCUEIL, VIDE] });
    await openTrads();

    const accueil = (await screen.findByText("Écrans d'accueil")).closest("li") as HTMLElement;
    expect(within(accueil).getByText("accueil")).toBeInTheDocument();
    expect(within(accueil).getByText("en-US 2/2")).toBeInTheDocument();
    expect(within(accueil).getByText("fr-FR 1/2")).toBeInTheDocument();
  });

  it("marks an empty context as empty rather than fully covered", async () => {
    routes({ status: 200, body: [VIDE] });
    await openTrads();

    const vide = (await screen.findByText("Encore vide")).closest("li") as HTMLElement;
    expect(within(vide).getByText("Empty")).toBeInTheDocument();
    expect(within(vide).queryByText("en-US 0/0")).not.toBeInTheDocument();
  });

  it("creates a context, the technical name following the label", async () => {
    const calls = routes(
      [
        { status: 200, body: [] },
        { status: 200, body: [ACCUEIL] },
      ],
      { [`POST ${ROUTE}`]: { status: 201, body: ACCUEIL } },
    );
    await openTrads();
    fireEvent.click(await screen.findByText("Add a context"));

    fill("Label", "Écrans d'accueil");
    expect(screen.getByLabelText("Technical name")).toHaveValue("ecrans-d-accueil");
    fill("Technical name", "accueil");
    fireEvent.click(screen.getByText("Create the context"));

    expect(await screen.findByText("Écrans d'accueil")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${ROUTE}`)?.body).toEqual({
      name: "accueil",
      label: "Écrans d'accueil",
    });
  });

  it("says which context already holds the technical name", async () => {
    routes(
      { status: 200, body: [ACCUEIL] },
      {
        [`POST ${ROUTE}`]: {
          status: 409,
          body: { detail: { code: "contexte_pris", label: "Écrans d'accueil" } },
        },
      },
    );
    await openTrads();
    fireEvent.click(await screen.findByText("Add a context"));
    fill("Label", "Autre");

    fireEvent.click(screen.getByText("Create the context"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "already taken by the context “Écrans d'accueil”",
    );
  });

  it("says the technical name is frozen before it is chosen", async () => {
    routes({ status: 200, body: [] });
    await openTrads();

    fireEvent.click(await screen.findByText("Add a context"));

    expect(screen.getByText(/frozen after creation/)).toBeInTheDocument();
  });

  it("renames the label and sends only the label", async () => {
    const calls = routes(
      [
        { status: 200, body: [ACCUEIL] },
        { status: 200, body: [{ ...ACCUEIL, label: "Accueil du terminal" }] },
      ],
      {
        [`PUT /api/workspaces/retrait/trads/accueil?branch=edition`]: {
          status: 200,
          body: { ...ACCUEIL, label: "Accueil du terminal" },
        },
      },
    );
    await openTrads();

    fireEvent.click(await screen.findByText("Rename"));
    fill("Label", "Accueil du terminal");
    fireEvent.click(screen.getByText("Save the label"));

    expect(await screen.findByText("Accueil du terminal")).toBeInTheDocument();
    const call = calls.find((c) => c.key.startsWith("PUT /api/workspaces/retrait/trads/accueil"));
    expect(call?.body).toEqual({ label: "Accueil du terminal" });
  });

  it("announces the keys and values a populated deletion takes with it", async () => {
    routes(
      { status: 200, body: [ACCUEIL] },
      {
        [`GET /api/workspaces/retrait/trads/accueil/removal?branch=edition`]: {
          status: 200,
          body: { keys: 2, values: 3 },
        },
      },
    );
    await openTrads();

    fireEvent.click(await screen.findByText("Delete"));

    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText(/2 key\(s\) and 3 value\(s\)/);
    // Dire aussi que rien n'est perdu : c'est un commit sur la branche de travail.
    expect(dialog).toHaveTextContent(/undone like any other configuration change/);
  });

  it("asks a plain confirmation for an empty context", async () => {
    routes(
      { status: 200, body: [VIDE] },
      {
        [`GET /api/workspaces/retrait/trads/vide/removal?branch=edition`]: {
          status: 200,
          body: { keys: 0, values: 0 },
        },
      },
    );
    await openTrads();

    fireEvent.click(await screen.findByText("Delete"));

    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText(/holds no key/);
    expect(dialog).not.toHaveTextContent("will disappear");
  });

  it("deletes the context once confirmed", async () => {
    const calls = routes(
      [
        { status: 200, body: [VIDE] },
        { status: 200, body: [] },
      ],
      {
        [`GET /api/workspaces/retrait/trads/vide/removal?branch=edition`]: {
          status: 200,
          body: { keys: 0, values: 0 },
        },
        [`DELETE /api/workspaces/retrait/trads/vide?branch=edition`]: {
          status: 200,
          body: { keys: 0, values: 0 },
        },
      },
    );
    await openTrads();
    fireEvent.click(await screen.findByText("Delete"));
    const dialog = await screen.findByRole("dialog");

    fireEvent.click(within(dialog).getByRole("button", { name: "Delete the context" }));

    expect(await screen.findByText("No translation context on this branch.")).toBeInTheDocument();
    expect(
      calls.some((c) => c.key === `DELETE /api/workspaces/retrait/trads/vide?branch=edition`),
    ).toBe(true);
  });

  it("names a directory that git carries without a declared label", async () => {
    routes({
      status: 200,
      body: [
        { name: "venu-dailleurs", label: "venu-dailleurs", keys: 1, translated: {}, obsolete: {} },
      ],
    });
    await openTrads();

    // Le nom technique fait office de libellé : il apparaît aux deux places de la ligne.
    const found = await screen.findAllByText("venu-dailleurs");
    expect(found).toHaveLength(2);
    const row = found[0]?.closest("li") as HTMLElement;
    expect(within(row).getByText("1")).toBeInTheDocument();
  });

  it("names the unreadable file instead of failing silently", async () => {
    routes({
      status: 422,
      body: { detail: { code: "trads_illisible", path: "trads/accueil/en-US.yaml" } },
    });
    await openTrads();

    expect(await screen.findByRole("alert")).toHaveTextContent("trads/accueil/en-US.yaml");
  });

  it("says nothing can be changed on a read-only branch", async () => {
    routes({ status: 200, body: [ACCUEIL] });
    // Sans prise de main sur la branche enfant, rien ne s'y modifie (story 9def0adc).
    mockApi({
      ...SETTINGS,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      "GET /api/workspaces/retrait/holds": { status: 200, body: [] },
      [`GET ${ROUTE}`]: { status: 200, body: [ACCUEIL] },
    });
    await openTrads();
    await screen.findByText("Écrans d'accueil");

    expect(screen.queryByText("Add a context")).not.toBeInTheDocument();
    expect(screen.queryByText("Delete")).not.toBeInTheDocument();
    expect(screen.queryByText("Rename")).not.toBeInTheDocument();
  });
});

describe("TradsScreen — cultures retirées", () => {
  it("counts what a culture left out of the workspace still holds", async () => {
    routes({ status: 200, body: [AVEC_OBSOLETE] });
    await openTrads();

    expect(await screen.findByText("ar-MA — 3 value(s)")).toBeInTheDocument();
  });

  it("says the values will not come back before cleaning them up", async () => {
    const calls = routes(
      [
        { status: 200, body: [AVEC_OBSOLETE] },
        { status: 200, body: [ACCUEIL] },
      ],
      {
        [`DELETE /api/workspaces/retrait/trads/accueil/obsolete/ar-MA?branch=edition`]: {
          status: 200,
          body: { keys: 0, values: 3 },
        },
      },
    );
    await openTrads();

    fireEvent.click(await screen.findByText("Clean up"));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("3 value(s) in ar-MA will disappear");
    expect(dialog).toHaveTextContent(/will not come back if you add it again/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Clean up" }));
    await vi.waitFor(() =>
      expect(calls.some((c) => c.key.includes("/obsolete/ar-MA"))).toBe(true),
    );
  });

  it("offers nothing to clean on a context whose cultures are all current", async () => {
    routes({ status: 200, body: [ACCUEIL] });
    await openTrads();
    await screen.findByText("Écrans d'accueil");

    expect(screen.queryByText("Clean up")).not.toBeInTheDocument();
    expect(screen.queryByText("Removed cultures")).not.toBeInTheDocument();
  });

  it("offers no cleanup on a read-only branch", async () => {
    mockApi({
      ...SETTINGS,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      "GET /api/workspaces/retrait/holds": { status: 200, body: [] },
      [`GET ${ROUTE}`]: { status: 200, body: [AVEC_OBSOLETE] },
    });
    await openTrads();

    // Le compte reste visible — c'est une information, pas un geste.
    expect(await screen.findByText("ar-MA — 3 value(s)")).toBeInTheDocument();
    expect(screen.queryByText("Clean up")).not.toBeInTheDocument();
  });
});
