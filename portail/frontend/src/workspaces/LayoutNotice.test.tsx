import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, modelListing, renderWorkspaces } from "./workspaceFixtures";

/**
 * Le cul-de-sac du 15/11/2026 : la branche était refusée en nommant la conversion, et
 * aucun écran ne l'offrait. Ces tests tiennent le bandeau qui l'offre.
 */
const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const LAYOUT = "GET /api/workspaces/retrait/layout?branch=edition";
const CONVERT = "POST /api/workspaces/retrait/layout/convert?branch=edition";
const A_JOUR = { kind: "a_jour", refusal: null, moves: 0, event_types: 0, conflicts: [] };
const ANCIENNE = {
  kind: "ancienne",
  refusal: "disposition_ancienne",
  moves: 12,
  event_types: 3,
  conflicts: [],
};

function routes(layout: unknown, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ...HELD,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    "GET /api/workspaces/retrait/versions?branch=edition": { status: 200, body: [] },
    "GET /api/workspaces/retrait/data-models?branch=edition": { status: 409, body: null },
    [LAYOUT]: { status: 200, body: layout },
    ...extra,
  };
}

function openModels(layout: unknown, extra: Record<string, unknown> = {}) {
  const calls = mockApi(routes(layout, extra) as never);
  renderWorkspaces({ id: "retrait", view: "dataModels", branch: "edition" });
  return calls;
}

describe("the old-layout notice", () => {
  it("says what blocks the branch and what converting would write", async () => {
    openModels(ANCIENNE);

    // Le refus, en toutes lettres : c'est sa CLEF BRUTE qui s'affichait sur la copie
    // d'écran du 15/11/2026.
    expect(await screen.findByText(/still uses the old layout/)).toBeInTheDocument();
    // L'effet AVANT le clic : un bouton qui écrit un commit s'annonce.
    expect(screen.getByText(/move 12 file\(s\)/)).toBeInTheDocument();
    expect(screen.getByText(/declare 3 event type\(s\)/)).toBeInTheDocument();
  });

  it("converts once confirmed, and never on the click alone", async () => {
    const calls = openModels(ANCIENNE, { [CONVERT]: { status: 200, body: { moved: 12 } } });

    fireEvent.click(await screen.findByRole("button", { name: "Convert the layout" }));

    // Discriminant : sans la confirmation, le clic écrirait DÉJÀ un commit sur la branche.
    const dialog = await screen.findByRole("dialog");
    expect(calls.filter((c) => c.key.startsWith("POST "))).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Convert the layout" }));

    await waitFor(() =>
      expect(calls.filter((c) => c.key.startsWith("POST ")).map((c) => c.key)).toEqual([
        "POST /api/workspaces/retrait/layout/convert?branch=edition",
      ]),
    );
  });

  it("shows nothing at all on a branch that is up to date", async () => {
    openModels(A_JOUR, {
      "GET /api/workspaces/retrait/data-models?branch=edition": {
        status: 200,
        body: modelListing(),
      },
    });

    // Attendre un rendu stable avant de conclure à l'absence : sinon le test passerait
    // parce que RIEN n'est encore arrivé.
    await screen.findByRole("heading", { name: /Retrait de colis/ });
    expect(screen.queryByText(/old layout/)).not.toBeInTheDocument();
  });

  it("explains why the button is absent to someone who has not taken hold", async () => {
    // Un bouton absent sans explication se lit comme une panne (Gael, 01/11/2026).
    const calls = mockApi({
      ...routes(ANCIENNE),
      "GET /api/workspaces/retrait/holds": { status: 200, body: [] },
    } as never);
    renderWorkspaces({ id: "retrait", view: "dataModels", branch: "edition" });

    expect(await screen.findByText(/Take hold of this branch/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Convert the layout" })).not.toBeInTheDocument();
    expect(calls.filter((c) => c.key.startsWith("POST "))).toHaveLength(0);
  });
});
