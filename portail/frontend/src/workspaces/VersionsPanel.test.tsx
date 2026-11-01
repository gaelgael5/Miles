import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { BRANCH_SCREEN, CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const VERSIONS = "/api/workspaces/retrait/versions";
const PUBLISH = "POST /api/workspaces/retrait/branches/edition/hold/publish";
const MODELS = "GET /api/workspaces/retrait/data-models?branch=edition";
const FREEZABLE = {
  [`GET ${VERSIONS}/freezable?branch=edition`]: { status: 200, body: { ok: true, reason: null, reports: [] } },
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
      ...BRANCH_SCREEN,
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
      ...BRANCH_SCREEN,
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
      ...BRANCH_SCREEN,
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
      ...BRANCH_SCREEN,
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
  async function refusAvec(problems: { path: string; code: string; detail?: string }[]) {
    mockApi({
      ...BRANCH_SCREEN,
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
            reports: [{ path: "storages/accounts.yaml", problems }],
          },
        },
      },
    });
    const panel = await openWorkshop();
    fireEvent.click(within(panel).getByText("Save a version"));
    fill("Label", "update site");
    fireEvent.click(within(panel).getByText("Save the version"));
    return panel;
  }

  it("describes an unknown property by naming it, instead of showing a raw key", async () => {
    // La copie d'écran du 01/11/2026 affichait « dataModels.problems.propriete_inconnue ».
    const panel = await refusAvec([
      { path: "index[0].colonnes[0]", code: "propriete_inconnue", detail: "$.site" },
    ]);

    expect(
      await within(panel).findByText(/property “\$\.site” does not exist in this storage/),
    ).toBeInTheDocument();
    expect(within(panel).queryByText(/dataModels\.problems/)).not.toBeInTheDocument();
  });

  it("falls back on a readable sentence when a code has no label at all", async () => {
    // La garde du backend l'empêche, mais si elle était un jour contournée, l'écran doit
    // rester diagnosticable : le code et son détail, jamais une clef de traduction.
    const panel = await refusAvec([
      { path: "quelque.part", code: "venu_d_ailleurs", detail: "$.x" },
    ]);

    const message = await within(panel).findByText(/venu_d_ailleurs/);
    expect(message).toHaveTextContent("$.x");
    expect(within(panel).queryByText(/dataModels\.problems/)).not.toBeInTheDocument();
  });

  function panelWith(freezable: {
    ok: boolean;
    reason: string | null;
    reports?: { path: string; problems: { path: string; code: string; detail?: string }[] }[];
  }) {
    mockApi({
      ...BRANCH_SCREEN,
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...BRANCHES,
      [MODELS]: { status: 200, body: [] },
      [`GET ${VERSIONS}?branch=edition`]: { status: 200, body: [] },
      [`GET ${VERSIONS}/freezable?branch=edition`]: {
        status: 200,
        body: { reports: [], ...freezable },
      },
    });
    return openWorkshop();
  }

  it("shows what fails the rules on arrival, without anyone clicking", async () => {
    // « il faudrait que le message d'erreur arrive avant que j'aie envie de commiter »
    // (Gael, 01/11/2026). Jusque-là on ne l'apprenait qu'après avoir demandé à figer.
    const panel = await panelWith({
      ok: false,
      reason: "parametrage_invalide",
      reports: [
        {
          path: "storages/accounts.yaml",
          problems: [
            { path: "index[0].colonnes[0]", code: "propriete_inconnue", detail: "$.site" },
          ],
        },
      ],
    });

    expect(await within(panel).findByText("storages/accounts.yaml")).toBeInTheDocument();
    expect(
      within(panel).getByText(/property “\$\.site” does not exist in this storage/),
    ).toBeInTheDocument();
    expect(within(panel).getByText("Save a version")).toBeDisabled();
    // Rien n'a été envoyé : l'écran n'a pas eu à ESSAYER pour savoir.
    expect(within(panel).queryByRole("form")).not.toBeInTheDocument();
  });

  it("shows them even when something else blocks first, so publishing is not wasted", async () => {
    // « publiez d'abord » et « ces fichiers ne passent pas » sont deux choses : celui qui
    // publie a le droit de savoir que le figement échouera ensuite.
    const panel = await panelWith({
      ok: false,
      reason: "publication_requise",
      reports: [{ path: "", problems: [{ path: "comptes/x.yaml", code: "emplacement_inattendu" }] }],
    });

    expect(await within(panel).findByText(/not published yet/)).toBeInTheDocument();
    expect(within(panel).getByText(/unexpected location/)).toBeInTheDocument();
  });

  it("greys the button out while changes are not published, and says so", async () => {
    const panel = await panelWith({ ok: false, reason: "publication_requise" });

    expect(await within(panel).findByText(/not published yet/)).toBeInTheDocument();
    expect(within(panel).getByText("Save a version")).toBeDisabled();
  });

  it("offers to publish right here, and re-reads what blocks once it is done", async () => {
    const calls = mockApi({
      ...BRANCH_SCREEN,
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...BRANCHES,
      [MODELS]: { status: 200, body: [] },
      [`GET ${VERSIONS}?branch=edition`]: { status: 200, body: [] },
      // La seconde lecture est celle d'après la publication : plus rien n'empêche.
      [`GET ${VERSIONS}/freezable?branch=edition`]: [
        { status: 200, body: { ok: false, reason: "publication_requise" } },
        { status: 200, body: { ok: true, reason: null, reports: [] } },
      ],
      [PUBLISH]: { status: 200, body: { published: 2 } },
    });
    const panel = await openWorkshop();

    fireEvent.click(await within(panel).findByText("Publish"));

    expect(await within(panel).findByText("2 changes published.")).toBeInTheDocument();
    expect(calls.some((c) => c.key === PUBLISH)).toBe(true);
    // Le bouton se rallume SANS geste : la clé de cache des versions porte le même slug
    // que la prise de main, donc l'invalidation de la publication l'atteint.
    expect(await within(panel).findByText("Save a version")).toBeEnabled();
  });

  it("names the refusal of a publication instead of showing a version error", async () => {
    mockApi({
      ...BRANCH_SCREEN,
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...BRANCHES,
      [MODELS]: { status: 200, body: [] },
      [`GET ${VERSIONS}?branch=edition`]: { status: 200, body: [] },
      [`GET ${VERSIONS}/freezable?branch=edition`]: {
        status: 200,
        body: { ok: false, reason: "publication_requise" },
      },
      [PUBLISH]: { status: 409, body: { detail: { code: "branche_bougee" } } },
    });
    const panel = await openWorkshop();

    fireEvent.click(await within(panel).findByText("Publish"));

    // Le vocabulaire des refus de prise de main, et pas celui des versions : ce sont deux
    // familles de codes, et les confondre rendrait « erreur inattendue » sur un refus qui
    // a un nom.
    expect(await within(panel).findByRole("alert")).toBeInTheDocument();
    expect(within(panel).queryByText(/unexpected/i)).not.toBeInTheDocument();
  });

  it("greys it out when nothing changed since the last version", async () => {
    const panel = await panelWith({ ok: false, reason: "rien_a_figer" });

    expect(await within(panel).findByText(/Nothing changed since the last version/)).toBeInTheDocument();
    expect(within(panel).getByText("Save a version")).toBeDisabled();
    // Pas de bouton de publication ici : rien n'est en attente de l'être, et l'offrir
    // proposerait un geste que le serveur refuserait.
    expect(within(panel).queryByText("Publish")).not.toBeInTheDocument();
  });

  it("leaves it usable when there is something to freeze", async () => {
    const panel = await panelWith({ ok: true, reason: null });

    expect(await within(panel).findByText("No version saved yet.")).toBeInTheDocument();
    expect(within(panel).getByText("Save a version")).toBeEnabled();
    expect(within(panel).queryByText("Publish")).not.toBeInTheDocument();
  });
});
