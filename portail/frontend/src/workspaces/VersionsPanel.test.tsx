import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const VERSIONS = "/api/workspaces/retrait/versions";
const MODELS = "GET /api/workspaces/retrait/data-models?branch=edition";
const FREEZABLE = {
  [`GET ${VERSIONS}/freezable?branch=edition`]: { status: 200, body: { ok: true, reason: null } },
};
const BRANCHES = {
  "GET /api/workspaces/retrait/branches": {
    status: 200,
    body: [{ slug: "atelier", label: "atelier", branch: "back/retrait/atelier", base: true }],
  },
};
const V1 = {
  number: 1,
  label: "Recette du 21 octobre",
  commit: "0123456789abcdef0123456789abcdef01234567",
  author: "admin via Miles <admin@local.miles.invalid>",
  saved_at: "2026-10-21T15:00:00Z",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openWorkshop() {
  // Le panneau des versions est sur l'écran de la branche : une version la fige en entier.
  renderWorkspaces({ id: "retrait", view: "branch", branch: "edition" });
  expect(
    await screen.findByRole("heading", { name: "Retrait de colis — branch edition" }),
  ).toBeInTheDocument();
  return screen.findByRole("region", { name: "Versions of the work branch" });
}

describe("VersionsPanel", () => {
  it("saves a version with its label, then lists it", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...BRANCHES,
      ...FREEZABLE,
      [MODELS]: { status: 200, body: [] },
      [`GET ${VERSIONS}?branch=edition`]: [
        { status: 200, body: [] },
        { status: 200, body: [V1] },
      ],
      [`POST ${VERSIONS}?branch=edition`]: { status: 201, body: V1 },
    });
    const panel = await openWorkshop();
    expect(await within(panel).findByText("No version saved yet.")).toBeInTheDocument();

    fireEvent.click(within(panel).getByText("Save a version"));
    fill("Label", "Recette du 21 octobre");
    fireEvent.click(within(panel).getByText("Save the version"));

    expect(await within(panel).findByText("Version 1 — Recette du 21 octobre")).toBeInTheDocument();
    expect(within(panel).getByText("0123456789")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${VERSIONS}?branch=edition`)?.body).toEqual({
      label: "Recette du 21 octobre",
    });
  });

  it("shows, file by file, why the configuration cannot be frozen", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...BRANCHES,
      ...FREEZABLE,
      [MODELS]: { status: 200, body: [] },
      [`GET ${VERSIONS}?branch=edition`]: { status: 200, body: [] },
      [`POST ${VERSIONS}?branch=edition`]: {
        status: 422,
        body: {
          detail: {
            code: "parametrage_invalide",
            reports: [
              { path: "", problems: [{ path: "prod", code: "dossier_d_environnement", detail: null }] },
              {
                path: "shared/messages/colis.yaml",
                problems: [{ path: "proprietes.p.modele", code: "modele_inconnu", detail: "personne" }],
              },
            ],
          },
        },
      },
    });
    const panel = await openWorkshop();
    fireEvent.click(within(panel).getByText("Save a version"));
    fill("Label", "Ne passera pas");
    fireEvent.click(within(panel).getByText("Save the version"));

    const alert = await within(panel).findByRole("alert");
    expect(alert).toHaveTextContent("The configuration does not pass the rules: nothing was frozen.");
    expect(alert).toHaveTextContent("Repository layout");
    expect(alert).toHaveTextContent("folder named after an environment");
    expect(alert).toHaveTextContent("shared/messages/colis.yaml");
    expect(alert).toHaveTextContent("proprietes.p.modele — model “personne” does not exist");
  });

  it("says there is nothing to freeze", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...BRANCHES,
      ...FREEZABLE,
      [MODELS]: { status: 200, body: [] },
      [`GET ${VERSIONS}?branch=edition`]: { status: 200, body: [V1] },
      [`POST ${VERSIONS}?branch=edition`]: { status: 409, body: { detail: "rien_a_figer" } },
    });
    const panel = await openWorkshop();
    fireEvent.click(within(panel).getByText("Save a version"));
    fill("Label", "Encore");
    fireEvent.click(within(panel).getByText("Save the version"));

    expect(
      await within(panel).findByText("Nothing changed since the last version: nothing to freeze."),
    ).toBeInTheDocument();
  });

  it("returns to a version after confirmation, by a new commit", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...BRANCHES,
      ...FREEZABLE,
      [MODELS]: { status: 200, body: [] },
      [`GET ${VERSIONS}?branch=edition`]: { status: 200, body: [V1] },
      [`POST ${VERSIONS}/1/restore?branch=edition`]: { status: 200, body: { commit: "fedcba98765432100000" } },
    });
    const panel = await openWorkshop();
    fireEvent.click(await within(panel).findByText("Return to this version"));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Later versions remain, nothing is erased.");

    fireEvent.click(within(dialog).getByRole("button", { name: "Return to this version" }));

    expect(
      await within(panel).findByText("Back to this version, by a new commit fedcba9876."),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.key === `POST ${VERSIONS}/1/restore?branch=edition`)).toBe(true);
  });
});

describe("the version button knows what the server will refuse (25/10/2026)", () => {
  function panelWith(freezable: { ok: boolean; reason: string | null }) {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...BRANCHES,
      [MODELS]: { status: 200, body: [] },
      [`GET ${VERSIONS}?branch=edition`]: { status: 200, body: [] },
      [`GET ${VERSIONS}/freezable?branch=edition`]: { status: 200, body: freezable },
    });
    return openWorkshop();
  }

  it("greys the button out while changes are not published, and says so", async () => {
    const panel = await panelWith({ ok: false, reason: "publication_requise" });

    expect(await within(panel).findByText(/not published yet/)).toBeInTheDocument();
    expect(within(panel).getByText("Save a version")).toBeDisabled();
  });

  it("greys it out when nothing changed since the last version", async () => {
    const panel = await panelWith({ ok: false, reason: "rien_a_figer" });

    expect(await within(panel).findByText(/Nothing changed since the last version/)).toBeInTheDocument();
    expect(within(panel).getByText("Save a version")).toBeDisabled();
  });

  it("leaves it usable when there is something to freeze", async () => {
    const panel = await panelWith({ ok: true, reason: null });

    expect(await within(panel).findByText("No version saved yet.")).toBeInTheDocument();
    expect(within(panel).getByText("Save a version")).toBeEnabled();
  });
});
