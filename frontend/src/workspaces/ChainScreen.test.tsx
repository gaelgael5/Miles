import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/transformations";
const Q = "?branch=edition";
const CHAIN = {
  slug: "comptes-import",
  label: "Import des comptes",
  steps: [
    {
      name: "normaliser",
      template: '{ "ref": $.colis.ref }',
      target: null,
      source_model: null,
      destination_model: null,
    },
    {
      name: "statut",
      template: '"ok"',
      target: "$.statut",
      source_model: null,
      destination_model: null,
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function openChain() {
  renderWorkspaces({ id: "retrait", view: "transformations", branch: "edition", chain: "comptes-import" });
}

describe("ChainsScreen", () => {
  it("creates a chain with its label and proposed slug, then opens it", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`PUT ${ROUTE}/import-des-comptes${Q}`]: {
        status: 200,
        body: { slug: "import-des-comptes", label: "Import des comptes", steps: [] },
      },
      [`GET ${ROUTE}/import-des-comptes${Q}`]: {
        status: 200,
        body: { slug: "import-des-comptes", label: "Import des comptes", steps: [] },
      },
    });
    renderWorkspaces({ id: "retrait", view: "transformations", branch: "edition" });
    expect(await screen.findByText("No transformation chain on this branch.")).toBeInTheDocument();

    fireEvent.click(screen.getByText("New chain"));
    fill("Label", "Import des comptes");
    expect(screen.getByLabelText("Slug")).toHaveValue("import-des-comptes");
    fireEvent.click(screen.getByText("Create the chain"));

    expect(await screen.findByText(/No step yet/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === `PUT ${ROUTE}/import-des-comptes${Q}`)?.body).toEqual({
      label: "Import des comptes",
      steps: [],
    });
  });
});

describe("ChainsScreen list", () => {
  it("opens a chain from its whole row, with no Open button", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}${Q}`]: {
        status: 200,
        body: [{ slug: CHAIN.slug, label: CHAIN.label, steps: 2 }],
      },
      [`GET ${ROUTE}/${CHAIN.slug}${Q}`]: { status: 200, body: CHAIN },
      [`GET ${ROUTE}/${CHAIN.slug}/sample${Q}`]: { status: 200, body: { sample: null } },
    });
    renderWorkspaces({ id: "retrait", view: "transformations", branch: "edition" });
    const title = await screen.findByRole("button", { name: CHAIN.label });
    const row = title.closest("li") as HTMLElement;

    expect(within(row).queryByRole("button", { name: "Open" })).toBeNull();
    fireEvent.click(title);

    expect(await screen.findByRole("button", { name: "normaliser" })).toBeInTheDocument();
  });
});

describe("ChainScreen", () => {
  it("reorders the steps and saves them in the chosen order", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
      [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: { sample: null } },
      [`PUT ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    openChain();
    const second = await screen.findByRole("listitem", { name: "Step 2" });

    fireEvent.click(within(second).getByText("Move up"));
    fireEvent.click(screen.getByText("Save the chain"));

    expect(await screen.findByText("Chain saved.")).toBeInTheDocument();
    const body = calls.find((c) => c.key === `PUT ${ROUTE}/comptes-import${Q}`)?.body as {
      steps: { name: string }[];
    };
    expect(body.steps.map((s) => s.name)).toEqual(["statut", "normaliser"]);
  });

  it("saves with Ctrl+S from a step field, the save button standing at the top", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
      [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: { sample: null } },
      [`PUT ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    openChain();
    // Le label de la chaîne : le seul champ restant sur cet écran depuis que les étapes
    // sont des lignes (24/10/2026).
    const field = await screen.findByDisplayValue("Import des comptes");
    // En haut à droite : dans l'en-tête de la page, avec le titre (caad743d).
    const head = screen.getByRole("heading", { level: 1 }).closest(".page-head") as HTMLElement;
    expect(within(head).getByRole("button", { name: "Save the chain" })).toBeInTheDocument();

    fireEvent.keyDown(field, { key: "s", ctrlKey: true });

    expect(await screen.findByText("Chain saved.")).toBeInTheDocument();
    expect(calls.filter((c) => c.key === `PUT ${ROUTE}/comptes-import${Q}`)).toHaveLength(1);
  });

  it("tries the chain on a sample and shows the message after each step", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
      [`GET ${ROUTE}/comptes-import/sample${Q}`]: {
        status: 200,
        body: { sample: '{"colis": {"ref": "C-42"}}' },
      },
      "POST /api/transformations/check": {
        status: 200,
        body: {
          valid: true,
          problems: [],
          trace: [{ ref: "C-42" }, { ref: "C-42", statut: "ok" }],
          failure: null,
        },
      },
    });
    openChain();
    // L'échantillon vient du serveur : on attend qu'il soit là, sinon l'essai partirait
    // sur rien et le test passerait pour une mauvaise raison.
    await screen.findByText(/Saved —/);

    fireEvent.click(screen.getByText("Run"));

    expect(await screen.findByText("After step 2")).toBeInTheDocument();
    expect(screen.getByText(/"statut": "ok"/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/transformations/check")?.body).toEqual({
      steps: CHAIN.steps.map((s) => ({ template: s.template, target: s.target })),
      sample: { colis: { ref: "C-42" } },
    });
  });

  it("shows each refusal next to its step and an invalid sample before running", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
      [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: { sample: "{" } },
      [`PUT ${ROUTE}/comptes-import${Q}`]: {
        status: 422,
        body: {
          detail: {
            code: "chaine_invalide",
            problems: [
              { step: 1, code: "cible_invalide", detail: "$.l[*]", line: null, column: null, violations: [] },
            ],
          },
        },
      },
    });
    openChain();
    // L'échantillon enregistré est illisible : l'écran le dit avant qu'on tente l'essai.
    expect(await screen.findByText("The sample is not valid JSON.")).toBeInTheDocument();
    expect(screen.getByText("Run")).toBeDisabled();

    fireEvent.click(screen.getByText("Save the chain"));

    const second = await screen.findByRole("listitem", { name: "Step 2" });
    expect(await within(second).findByText(/Target “\$\.l\[\*\]” is not a single path/)).toBeInTheDocument();
  });

  it("deletes the chain only after confirmation", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
      [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: { sample: null } },
      [`DELETE ${ROUTE}/comptes-import${Q}`]: { status: 204 },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    openChain();
    fireEvent.click(await screen.findByText("Delete the chain"));
    expect(calls.some((c) => c.key.startsWith("DELETE"))).toBe(false);

    fireEvent.click(screen.getAllByRole("button", { name: "Delete the chain" }).at(-1) as HTMLElement);

    expect(await screen.findByText("No transformation chain on this branch.")).toBeInTheDocument();
    expect(calls.some((c) => c.key === `DELETE ${ROUTE}/comptes-import${Q}`)).toBe(true);
  });
});

describe("test source sample (24/10/2026)", () => {
  it("is saved from a window that then gives way to a single line", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
      [`GET ${ROUTE}/comptes-import/sample${Q}`]: [
        { status: 200, body: { sample: null } },
        { status: 200, body: { sample: '{"colis": 1}' } },
      ],
      [`PUT ${ROUTE}/comptes-import/sample${Q}`]: {
        status: 200,
        body: { sample: '{"colis": 1}' },
      },
    });
    openChain();

    fireEvent.click(await screen.findByText("Save a sample"));
    fill("Sample message (JSON, optional)", '{"colis": 1}');
    fireEvent.click(screen.getByText("Save the sample"));

    // La fenêtre s'efface, il ne reste qu'une ligne.
    expect(await screen.findByText(/Saved —/)).toBeInTheDocument();
    expect(screen.queryByText("Save the sample")).toBeNull();
    expect(calls.find((c) => c.key === `PUT ${ROUTE}/comptes-import/sample${Q}`)?.body).toEqual({
      sample: '{"colis": 1}',
    });
  });

  it("pastes from the clipboard, and says so when the browser refuses", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
      [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: { sample: null } },
    });
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { readText: () => Promise.reject(new Error("refusé")) },
    });
    openChain();

    fireEvent.click(await screen.findByText("Save a sample"));
    fireEvent.click(screen.getByText("Paste from the clipboard"));

    // Le refus se dit : la saisie à la main reste possible, encore faut-il le savoir.
    expect(await screen.findByText(/refused to read the clipboard/)).toBeInTheDocument();
  });
});

const SAVED = {
  ...CHAIN,
  steps: CHAIN.steps.map((s, i) => (i === 0 ? { ...s, template: '{ "ref": 1 }' } : s)),
};

describe("step page (24/10/2026)", () => {
  it("opens from the whole row, the template having left the chain screen", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
      [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: { sample: null } },
    });
    openChain();

    // Le template n'est plus sur l'écran de la chaîne.
    expect(await screen.findByRole("button", { name: "normaliser" })).toBeInTheDocument();
    expect(screen.queryByLabelText("JSLT template")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "normaliser" }));

    expect(await screen.findByRole("heading", { level: 1, name: "normaliser" })).toBeInTheDocument();
    expect(screen.getByLabelText("JSLT template")).toHaveValue('{ "ref": $.colis.ref }');
  });

  it("saves the step through the whole chain, the step having no life of its own", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: [
        { status: 200, body: CHAIN },
        // Après enregistrement, le serveur rend la chaîne telle qu'il l'a écrite.
        { status: 200, body: SAVED },
      ],
      [`GET ${ROUTE}/comptes-import/sample${Q}`]: { status: 200, body: { sample: null } },
      [`PUT ${ROUTE}/comptes-import${Q}`]: { status: 200, body: SAVED },
    });
    renderWorkspaces({
      id: "retrait",
      view: "transformations",
      branch: "edition",
      chain: "comptes-import",
      step: "normaliser",
    });

    await screen.findByLabelText("JSLT template");
    fill("JSLT template", '{ "ref": 1 }');
    fireEvent.click(screen.getByText("Save the chain"));

    expect(await screen.findByText("Chain saved.")).toBeInTheDocument();
    const body = calls.find((c) => c.key === `PUT ${ROUTE}/comptes-import${Q}`)?.body as {
      steps: { name: string; template: string }[];
    };
    expect(body.steps.map((s) => s.template)).toEqual(['{ "ref": 1 }', '"ok"']);
  });
});
