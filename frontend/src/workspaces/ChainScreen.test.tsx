import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "work/atelier" };
const ROUTE = "/api/workspaces/retrait/transformations";
const Q = "?branch=edition";
const CHAIN = {
  slug: "comptes-import",
  label: "Import des comptes",
  steps: [
    { name: "normaliser", template: '{ "ref": $.colis.ref }', target: null },
    { name: "statut", template: '"ok"', target: "$.statut" },
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

describe("ChainScreen", () => {
  it("reorders the steps and saves them in the chosen order", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
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

  it("tries the chain on a sample and shows the message after each step", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
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
    await screen.findByText("Run");
    fill("Sample message (JSON, optional)", '{"colis": {"ref": "C-42"}}');

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
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
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
    await screen.findByText("Run");
    fill("Sample message (JSON, optional)", "{ pas du json");
    expect(await screen.findByText("The sample is not valid JSON.")).toBeInTheDocument();
    expect(screen.getByText("Run")).toBeDisabled();

    fireEvent.click(screen.getByText("Save the chain"));

    const second = await screen.findByRole("listitem", { name: "Step 2" });
    expect(await within(second).findByText(/Target “\$\.l\[\*\]” is not a single path/)).toBeInTheDocument();
  });

  it("deletes the chain only after confirmation", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}/comptes-import${Q}`]: { status: 200, body: CHAIN },
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
