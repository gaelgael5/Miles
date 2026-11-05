import { fireEvent, screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, renderWorkspaces } from "../workspaces/workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const Q = "?branch=edition";
const WS = "/api/workspaces/retrait";
const SPEC = { openapi: "3.1.0", info: { title: "rag", version: "1" }, paths: {} };
const SOURCE = {
  name: "crm",
  label: "CRM",
  storage: "sites",
  entries: [
    {
      kind: "web",
      source_model: "pudo/import-crm",
      chain: "import-crm",
      modes: { element: true, batch: false, file: false },
      split: "",
      unified_transaction: false,
      write_batch: 100,
    },
  ],
};
const CONTRACT = {
  slug: "rag",
  label: "rag",
  sens: "externe",
  versions: [
    {
      number: 1,
      title: "ragflow",
      openapi: "3.1.0",
      operations: 24,
      operation_list: [],
      removed: [],
      compared_with: null,
      warnings: [],
      imported_at: "2026-10-24T10:55:36Z",
      imported_by: "admin",
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Swagger viewer (25/10/2026)", () => {
  it("opens a contract version from its row, and reads that version's document", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${WS}/contracts${Q}`]: { status: 200, body: [] },
      [`GET ${WS}/contracts/rag${Q}`]: { status: 200, body: CONTRACT },
      [`GET ${WS}/contracts/rag/versions/1/openapi${Q}`]: { status: 200, body: SPEC },
    });
    renderWorkspaces({ id: "retrait", view: "contracts", branch: "edition", contract: "rag" });

    fireEvent.click(await screen.findByText("View in Swagger"));

    expect(await screen.findByTestId("swagger-spec")).toHaveTextContent('"openapi":"3.1.0"');
    expect(calls.some((c) => c.key === `GET ${WS}/contracts/rag/versions/1/openapi${Q}`)).toBe(
      true,
    );
  });

  it("opens with the document's description folded, and unfolds it on the chevron", async () => {
    // Gael, 05/11/2026 : la prose d'en-tête d'un contrat bavard repousse les adresses
    // hors de l'écran, donc elle arrive repliée. Ce qui se replie est elle, pas le
    // contrat — le document reste là, replié ou non.
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${WS}/contracts${Q}`]: { status: 200, body: [] },
      [`GET ${WS}/contracts/rag${Q}`]: { status: 200, body: CONTRACT },
      [`GET ${WS}/contracts/rag/versions/1/openapi${Q}`]: { status: 200, body: SPEC },
    });
    renderWorkspaces({ id: "retrait", view: "contracts", branch: "edition", contract: "rag" });
    fireEvent.click(await screen.findByText("View in Swagger"));

    expect(await screen.findByTestId("swagger-spec")).toBeInTheDocument();
    expect(screen.getByTestId("swagger-spec").closest(".spec-host")).toHaveClass("spec-folded");

    fireEvent.click(screen.getByRole("button", { name: "Show the description" }));

    expect(screen.getByTestId("swagger-spec").closest(".spec-host")).not.toHaveClass(
      "spec-folded",
    );
  });

  it("offers the document itself, downloadable in one click", async () => {
    // Un lien vers la MÊME adresse que l'écran lit : ce qu'on enregistre est exactement
    // ce qu'un appel rend, et il n'y a pas deux chemins par lesquels le contrat sort.
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${WS}/contracts${Q}`]: { status: 200, body: [] },
      [`GET ${WS}/contracts/rag${Q}`]: { status: 200, body: CONTRACT },
      [`GET ${WS}/contracts/rag/versions/1/openapi${Q}`]: { status: 200, body: SPEC },
    });
    renderWorkspaces({ id: "retrait", view: "contracts", branch: "edition", contract: "rag" });
    fireEvent.click(await screen.findByText("View in Swagger"));

    const lien = await screen.findByRole("link", { name: "Download" });
    expect(lien).toHaveAttribute("href", `${WS}/contracts/rag/versions/1/openapi${Q}`);
    expect(lien).toHaveAttribute("download", "rag-v1.openapi.json");
  });

  it("opens the API a source promises, derived from its declaration", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${WS}/storages${Q}`]: { status: 200, body: [] },
      [`GET ${WS}/data-models${Q}`]: { status: 200, body: [] },
      [`GET ${WS}/transformations${Q}`]: { status: 200, body: [] },
      [`GET ${WS}/sources${Q}`]: { status: 200, body: [] },
      [`GET ${WS}/sources/crm${Q}`]: { status: 200, body: SOURCE },
      [`GET ${WS}/sources/crm/openapi${Q}`]: { status: 200, body: SPEC },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition", source: "crm" });

    fireEvent.click(await screen.findByText("View the API in Swagger"));

    expect(await screen.findByTestId("swagger-spec")).toBeInTheDocument();
    // C'est l'API de la source qu'on lit, pas un contrat enregistré.
    expect(calls.some((c) => c.key === `GET ${WS}/sources/crm/openapi${Q}`)).toBe(true);
  });

  it("says plainly when the document cannot be read", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${WS}/storages${Q}`]: { status: 200, body: [] },
      [`GET ${WS}/data-models${Q}`]: { status: 200, body: [] },
      [`GET ${WS}/transformations${Q}`]: { status: 200, body: [] },
      [`GET ${WS}/sources${Q}`]: { status: 200, body: [] },
      [`GET ${WS}/sources/crm${Q}`]: { status: 200, body: SOURCE },
      [`GET ${WS}/sources/crm/openapi${Q}`]: { status: 502, body: { detail: "acces_depot" } },
    });
    renderWorkspaces({ id: "retrait", view: "sources", branch: "edition", source: "crm" });

    fireEvent.click(await screen.findByText("View the API in Swagger"));

    expect(await screen.findByText("The document could not be read.")).toBeInTheDocument();
  });
});
