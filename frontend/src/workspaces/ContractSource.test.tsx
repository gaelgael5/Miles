import { fireEvent, screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "work/atelier" };
const ROUTE = "/api/workspaces/retrait/contracts";
const YAML = "openapi: 3.1.0\ninfo: {title: Matériel, version: '2'}\npaths: {}\n";
const PREVIEW = { slug: "materiel", title: "Matériel", openapi: "3.1.0", operations: [], warnings: [] };
const CONTENT = "OpenAPI contract (YAML or JSON)";

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openImport() {
  renderWorkspaces();
  fireEvent.click(await screen.findByText("Contracts"));
  fireEvent.click(await screen.findByText("Import a contract"));
}

describe("ContractSource", () => {
  it("loads a chosen file into the contract text and reads it at once", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}`]: { status: 200, body: [] },
      [`POST ${ROUTE}/preview`]: { status: 200, body: PREVIEW },
    });
    await openImport();

    const file = new File([YAML], "materiel.yaml", { type: "application/yaml" });
    // jsdom n'a pas Blob.text(), que tous les navigateurs visés fournissent.
    Object.defineProperty(file, "text", { value: () => Promise.resolve(YAML) });
    fireEvent.change(screen.getByLabelText("From a file"), { target: { files: [file] } });

    expect(await screen.findByLabelText("Slug")).toHaveValue("materiel");
    expect(screen.getByLabelText(CONTENT)).toHaveValue(YAML);
    expect(calls.find((c) => c.key === `POST ${ROUTE}/preview`)?.body).toEqual({ content: YAML });
  });

  it("fetches an address through the back-office, then shows what will be imported", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}`]: { status: 200, body: [] },
      [`POST ${ROUTE}/fetch`]: { status: 200, body: { content: YAML } },
      [`POST ${ROUTE}/preview`]: { status: 200, body: PREVIEW },
    });
    await openImport();
    expect(screen.getByText("Fetch")).toBeDisabled();

    fill("From an address", "https://tiers.example/openapi.yaml");
    fireEvent.click(screen.getByText("Fetch"));

    expect(await screen.findByLabelText("Slug")).toHaveValue("materiel");
    expect(screen.getByLabelText(CONTENT)).toHaveValue(YAML);
    expect(calls.find((c) => c.key === `POST ${ROUTE}/fetch`)?.body).toEqual({
      url: "https://tiers.example/openapi.yaml",
    });
  });

  it("says why an address was not read, without touching the contract text", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}`]: { status: 200, body: [] },
      [`POST ${ROUTE}/fetch`]: [
        { status: 422, body: { detail: { code: "lecture_distante", reason: "statut", status: 404 } } },
        { status: 422, body: { detail: { code: "lecture_distante", reason: "adresse_interdite" } } },
      ],
    });
    await openImport();
    fill(CONTENT, "déjà là");

    fill("From an address", "https://tiers.example/absent.yaml");
    fireEvent.click(screen.getByText("Fetch"));
    expect(
      await screen.findByText("The address answered with status 404 instead of the contract."),
    ).toBeInTheDocument();

    fill("From an address", "http://127.0.0.1/");
    fireEvent.click(screen.getByText("Fetch"));
    expect(await screen.findByText(/leads to the back-office itself/)).toBeInTheDocument();
    expect(screen.getByLabelText(CONTENT)).toHaveValue("déjà là");
  });
});
