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

    // Ctrl+F5 et non F5 seul (Gael, 31/10/2026) : F5 seul est le rechargement du
    // navigateur, et le capturer privait d'un geste réflexe sur l'écran qui l'appelle.
    fireEvent.keyDown(screen.getByLabelText("JSLT template"), { key: "F5", ctrlKey: true });

    // Avant : `return` muet. Le bouton semblait cassé, et rien ne disait que c'était
    // l'échantillon — pas le template — qui était en cause.
    expect(await screen.findByText(/not readable JSON/)).toBeInTheDocument();
  });
});

describe("ChainStepScreen — la ligne fautive, montrée dans le code", () => {
  it("numbers the lines of the template", async () => {
    openStep();
    await screen.findByLabelText("JSLT template");

    // Le template de l'essai tient sur une ligne ; le numéro est là quand même.
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("marks the refused line in the gutter and over the code", async () => {
    openStep({ [`PUT ${ROUTE}/comptes-import${Q}`]: SYNTAX_REFUSAL });
    await screen.findByLabelText("JSLT template");
    fireEvent.change(screen.getByLabelText("JSLT template"), {
      target: { value: "{\n1\n2\n3\n4\n5\n6\n7\n8\n}" },
    });
    fireEvent.click(screen.getByText("Save the chain"));
    await screen.findByText(/line 9, column 2/);

    // La bande porte la ligne qu'elle désigne : sous jsdom aucun rectangle n'est
    // calculé, donc le test vérifie la ligne visée, pas les pixels où elle est posée.
    const band = document.querySelector(".template-error-line");
    expect(band).not.toBeNull();
    expect(band?.getAttribute("data-line")).toBe("9");
    expect(screen.getByText("9")).toHaveClass("gutter-error");
    expect(screen.getByText("8")).not.toHaveClass("gutter-error");
  });

  it("marks nothing while nothing is refused", async () => {
    openStep();
    await screen.findByLabelText("JSLT template");

    expect(document.querySelector(".template-error-line")).toBeNull();
  });
});

describe("ChainStepScreen — le document source, au clavier", () => {
  const SAMPLE = { sample: '{"Account": [{"PickupReference": "C-42", "Name": "Acme"}]}' };

  async function openSource(routes = { [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: SAMPLE } }) {
    openStep(routes);
    const editor = await screen.findByLabelText("JSLT template");
    await screen.findByText(/sample saved/);
    // Ctrl+Espace depuis l'éditeur : le bouton a été retiré le 31/10/2026, on ne
    // quitte plus l'endroit où l'on écrit pour chercher un chemin.
    fireEvent.keyDown(editor, { key: " ", ctrlKey: true });
    return editor as HTMLTextAreaElement;
  }

  it("inserts the JSONPath where the caret was, and closes", async () => {
    openStep({ [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: SAMPLE } });
    const editor = (await screen.findByLabelText("JSLT template")) as HTMLTextAreaElement;
    await screen.findByText(/sample saved/);
    // Le curseur POSÉ : `{ "ref": ` fait neuf caractères, et c'est là qu'on écrit.
    editor.setSelectionRange(9, 9);
    fireEvent.keyDown(editor, { key: " ", ctrlKey: true });
    const dialog = await screen.findByRole("dialog");

    // Sous un indice de tableau : c'est là que recopier à la main se trompe.
    fireEvent.click(within(dialog).getByTitle("Insert $.Account[0].PickupReference"));

    expect(editor).toHaveValue('{ "ref": $.Account[0].PickupReference$.colis.ref, }');
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("replaces the selection rather than pushing the path next to it", async () => {
    const editor = await openSource();
    screen.getByRole("dialog");
    // Rouvrir après avoir sélectionné `$.colis.ref` : le chemin doit le REMPLACER,
    // sans emporter la virgule qui suit.
    fireEvent.keyDown(editor, { key: "Escape" });
    editor.setSelectionRange(9, 20);
    fireEvent.keyDown(editor, { key: " ", metaKey: true });

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByTitle("Insert $.Account[0].Name"));

    expect(editor).toHaveValue('{ "ref": $.Account[0].Name, }');
  });

  it("opens on Command+Space too, for a Mac", async () => {
    openStep({ [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: SAMPLE } });
    const editor = await screen.findByLabelText("JSLT template");
    await screen.findByText(/sample saved/);

    fireEvent.keyDown(editor, { key: " ", metaKey: true });

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("stays shut on a bare Space, which is just typing", async () => {
    openStep({ [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: SAMPLE } });
    const editor = await screen.findByLabelText("JSLT template");
    await screen.findByText(/sample saved/);

    fireEvent.keyDown(editor, { key: " " });

    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says why nothing opens when the sample is not readable", async () => {
    openStep({
      [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: { sample: "{" } },
    });
    const editor = await screen.findByLabelText("JSLT template");
    await screen.findByText(/sample saved/);

    fireEvent.keyDown(editor, { key: " ", ctrlKey: true });

    // Une touche sans effet est le défaut qu'on vient de corriger sur F5 : on ne le
    // réintroduit pas en n'armant simplement pas le raccourci.
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(await screen.findByText(/no document to browse/)).toBeInTheDocument();
  });
});
