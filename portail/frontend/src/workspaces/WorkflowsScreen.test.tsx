import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/workflows";
const Q = "?branch=edition";

const RETRAIT = {
  name: "retrait_comptoir",
  label: "Retrait au comptoir",
  version: null,
  includes: ["shared.wf"],
  states: 2,
  problems: [],
};
// Valeurs DISCRIMINANTES face au premier : une version, un autre jeu d'inclusions, un
// autre nombre d'états. Deux workflows identiques laisseraient passer un écran qui
// affiche toujours la même ligne.
const LIVRAISON = {
  name: "livraison_domicile",
  label: "Livraison à domicile",
  version: 2,
  includes: ["shared.wf", "livraison.wf"],
  states: 4,
  problems: [],
};
const CASSE = {
  name: "casse",
  label: null,
  version: null,
  includes: [],
  states: 0,
  problems: [{ line: 2, column: 13, message: "mismatched input ''sans clef''" }],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkflowsScreen (16/11/2026)", () => {
  it("lists the workflow scripts of the branch with what each one declares", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [RETRAIT, LIVRAISON] },
    });
    renderWorkspaces({ id: "retrait", view: "workflows", branch: "edition" });

    const retrait = (await screen.findByText("retrait_comptoir")).closest("li");
    const livraison = screen.getByText("livraison_domicile").closest("li");
    expect(retrait).not.toBeNull();
    expect(livraison).not.toBeNull();

    // Le libellé, les états, la version et les inclusions de CHAQUE ligne : c'est la
    // sélection qui est en jeu, pas l'affichage d'une valeur.
    expect(within(retrait as HTMLElement).getByText("Retrait au comptoir")).toBeInTheDocument();
    expect(within(retrait as HTMLElement).getByText("2")).toBeInTheDocument();
    expect(within(retrait as HTMLElement).getByText("none")).toBeInTheDocument();
    expect(within(retrait as HTMLElement).getByText("shared.wf")).toBeInTheDocument();

    expect(within(livraison as HTMLElement).getByText("4")).toBeInTheDocument();
    // Dans l'ordre ÉCRIT : le chargeur du moteur visite les fragments dans cet ordre.
    expect(
      within(livraison as HTMLElement).getByText("shared.wf, livraison.wf"),
    ).toBeInTheDocument();
  });

  it("shows an unreadable script with its positioned problems, and keeps the rest listed", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [CASSE, RETRAIT] },
    });
    renderWorkspaces({ id: "retrait", view: "workflows", branch: "edition" });

    const casse = (await screen.findByText("casse")).closest("li");
    expect(casse).not.toBeNull();
    // Positionné comme le moteur le positionne : sans la ligne, on rouvre le fichier
    // pour chercher où.
    expect(within(casse as HTMLElement).getByText("2:13")).toBeInTheDocument();
    expect(
      within(casse as HTMLElement).getByText(/mismatched input/),
    ).toBeInTheDocument();
    expect(within(casse as HTMLElement).getByText(/Unreadable script/)).toBeInTheDocument();

    // Un script cassé ne noircit pas l'écran : l'autre est toujours là, complet.
    const retrait = screen.getByText("retrait_comptoir").closest("li");
    expect(within(retrait as HTMLElement).getByText("Retrait au comptoir")).toBeInTheDocument();
  });

  it("creates a workflow whose name is proposed with underscores, never dashes", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`POST ${ROUTE}${Q}`]: { status: 201, body: { ...RETRAIT, includes: [], states: 0 } },
    });
    renderWorkspaces({ id: "retrait", view: "workflows", branch: "edition" });
    expect(await screen.findByText("No workflow on this branch.")).toBeInTheDocument();

    fireEvent.click(screen.getByText("New workflow"));
    fill("Label", "Retrait au comptoir");

    // Le DSL du moteur refuse le tiret : la proposition doit donc porter des soulignés,
    // sinon le serveur refuse un nom que l'écran savait déjà invalide.
    expect(screen.getByLabelText("Name")).toHaveValue("retrait_au_comptoir");

    fill("Name", "retrait_comptoir");
    fireEvent.click(screen.getByText("Create"));

    // Le CORPS envoyé, et pas la ligne qui réapparaît : la liste est relue après coup, et
    // la relire ici ne prouverait que le contenu de la doublure.
    await vi.waitFor(() =>
      expect(calls).toContainEqual({
        key: `POST ${ROUTE}${Q}`,
        body: { name: "retrait_comptoir", label: "Retrait au comptoir" },
      }),
    );
  });

  it("names the file in the delete confirmation, because that is what an INCLUDE writes", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [RETRAIT] },
      [`DELETE ${ROUTE}/retrait_comptoir${Q}`]: { status: 204, body: null },
    });
    renderWorkspaces({ id: "retrait", view: "workflows", branch: "edition" });

    fireEvent.click(await screen.findByText("Delete"));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/workflows\/retrait_comptoir\.wf/)).toBeInTheDocument();
    // Dans le dialogue : le bouton de la ligne porte le même libellé, et viser l'écran
    // entier reviendrait à cliquer sur l'un ou l'autre selon l'ordre du DOM.
    fireEvent.click(within(dialog).getByText("Delete"));

    await vi.waitFor(() =>
      expect(calls).toContainEqual({
        key: `DELETE ${ROUTE}/retrait_comptoir${Q}`,
        body: undefined,
      }),
    );
  });

  it("offers no writing gesture on a branch one does not hold", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [RETRAIT] },
    });
    renderWorkspaces({ id: "retrait", view: "workflows", branch: "edition" });

    expect(await screen.findByText("retrait_comptoir")).toBeInTheDocument();
    // Ni création ni suppression : sans la main, l'écran se lit (story 9def0adc).
    expect(screen.queryByText("New workflow")).not.toBeInTheDocument();
    expect(screen.queryByText("Delete")).not.toBeInTheDocument();
  });
});
