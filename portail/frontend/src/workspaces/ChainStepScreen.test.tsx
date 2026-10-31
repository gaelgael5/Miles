import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { type Routes, mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, renderWorkspaces } from "./workspaceFixtures";

// L'écran d'une étape (Gael, 31/10/2026) : ce qu'il DIT quand il refuse, et le document
// source déplié. Les trois défauts corrigés ici étaient muets — un refus réduit à « voir
// les journaux », un F5 sans effet, une liste de violations jamais affichée.
const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/transformations";
const Q = "?branch=edition";
const CHAIN = {
  slug: "comptes-import",
  label: "Import des comptes",
  steps: [
    {
      name: "normaliser",
      template: '{ "ref": $.colis.ref, }',
      target: null,
      source_model: null,
      destination_model: null,
    },
  ],
};
// Le refus réel du serveur, relevé sur test1 le 31/10/2026 : une virgule de trop avant
// l'accolade fermante, et JSLT attend une clé de plus. Le serveur nomme la ligne, la
// colonne et ce qu'il a lu — c'est exactement ce que l'écran jetait.
const SYNTAX_REFUSAL = {
  status: 422,
  body: {
    detail: {
      code: "chaine_invalide",
      problems: [
        {
          step: 0,
          code: "syntaxe",
          detail: "mismatched input '}' expecting STRING (ligne 9, colonne 2)",
          line: 9,
          column: 2,
          violations: [],
        },
      ],
    },
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function openStep(routes: Routes = {}) {
  const calls = mockApi({
    ...HELD,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
    [`GET /api/workspaces/retrait/data-models${Q}`]: { status: 200, body: [] },
    [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: { sample: null } },
    ...routes,
  });
  renderWorkspaces({
    id: "retrait",
    view: "transformations",
    branch: "edition",
    chain: "comptes-import",
    step: "normaliser",
  });
  return calls;
}

describe("ChainStepScreen — ce que l'écran dit quand il refuse", () => {
  it("names the line, the column and what was read instead of pointing at the logs", async () => {
    openStep({ [`PUT ${ROUTE}/comptes-import${Q}`]: SYNTAX_REFUSAL });
    await screen.findByLabelText("JSLT template");

    fireEvent.change(screen.getByLabelText("JSLT template"), { target: { value: "{ }" } });
    fireEvent.click(screen.getByText("Save the chain"));

    expect(await screen.findByText(/line 9, column 2/)).toBeInTheDocument();
    expect(screen.getByText(/mismatched input/)).toBeInTheDocument();
    // Et PLUS le message qui renvoyait aux journaux : la réponse disait tout.
    expect(screen.queryByText(/back-office logs/)).toBeNull();
  });

  it("lists every construction out of the writing profile, not just the heading", async () => {
    const refusal = {
      status: 422,
      body: {
        detail: {
          code: "chaine_invalide",
          problems: [
            {
              step: 0,
              code: "hors_profil",
              detail: null,
              line: null,
              column: null,
              violations: [
                { construction: "let", detail: "x", line: 2, column: 3 },
                { construction: "def", detail: "f", line: 5, column: 1 },
              ],
            },
          ],
        },
      },
    };
    openStep({ [`PUT ${ROUTE}/comptes-import${Q}`]: refusal });
    await screen.findByLabelText("JSLT template");

    fireEvent.change(screen.getByLabelText("JSLT template"), { target: { value: "let x = 1 {}" } });
    fireEvent.click(screen.getByText("Save the chain"));

    // Le libellé du code finit par deux-points et annonce une liste : sans elle,
    // l'écran affichait une phrase suivie de rien. Plusieurs zones d'alerte coexistent
    // (le refus, puis le détail) : on cherche dans celle qui porte le code.
    const alerts = await screen.findAllByRole("alert");
    const detail = alerts.find((a) => /writing profile|profil d/.test(a.textContent ?? ""));
    expect(detail).toBeDefined();
    expect(within(detail as HTMLElement).getByText(/let/)).toBeInTheDocument();
    expect(within(detail as HTMLElement).getByText(/def/)).toBeInTheDocument();
  });

  it("says why running did nothing when the sample is not readable JSON", async () => {
    openStep({
      [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: { sample: "{" } },
    });
    // Attendre que l'échantillon soit LU : avant sa lecture, l'écran répond
    // « pas encore lu », ce qui est une autre branche que celle qu'on mesure.
    await screen.findByText(/sample saved/);

    fireEvent.click(screen.getByText("Run (F5)"));

    // Avant : `return` muet. Le bouton semblait cassé, et rien ne disait que c'était
    // l'échantillon — pas le template — qui était en cause.
    expect(await screen.findByText(/not readable JSON/)).toBeInTheDocument();
  });
});

describe("ChainStepScreen — le document source déplié", () => {
  const SAMPLE = { sample: '{"Account": [{"PickupReference": "C-42", "Name": "Acme"}]}' };

  it("copies the JSONPath of the property that was clicked", async () => {
    const written: string[] = [];
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: {
        writeText: (text: string) => {
          written.push(text);
          return Promise.resolve();
        },
      },
    });
    openStep({ [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: SAMPLE } });
    await screen.findByLabelText("JSLT template");

    fireEvent.click(screen.getByText("Source data"));
    const dialog = await screen.findByRole("dialog");
    // Sous un indice de tableau : c'est là que recopier à la main se trompe.
    fireEvent.click(within(dialog).getByTitle('Copy $.Account[0].PickupReference'));

    expect(written).toEqual(["$.Account[0].PickupReference"]);
    expect(await within(dialog).findByText("copied")).toBeInTheDocument();
  });

  it("says so when the browser refuses the clipboard", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: () => Promise.reject(new Error("refusé")) },
    });
    openStep({ [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: SAMPLE } });
    await screen.findByLabelText("JSLT template");

    fireEvent.click(screen.getByText("Source data"));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByTitle('Copy $.Account[0].Name'));

    // Sans ce message, un clic sans effet laisse croire à une copie : c'est l'ancien
    // contenu du presse-papiers qui serait collé dans le template.
    expect(await within(dialog).findByText(/refused the clipboard/)).toBeInTheDocument();
  });

  it("offers nothing to explore when the sample is not readable", async () => {
    openStep({
      [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: { sample: "{" } },
    });
    await screen.findByText(/sample saved/);

    expect(screen.getByText("Source data")).toBeDisabled();
  });
});
