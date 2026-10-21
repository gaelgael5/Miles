import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "work/atelier" };
const ROUTE = "/api/workspaces/retrait/contracts";
const YAML = "openapi: 3.0.3\ninfo: {title: Suivi des demandes, version: '1'}\npaths: {}\n";
const PREVIEW = {
  slug: "suivi-des-demandes",
  title: "Suivi des demandes",
  openapi: "3.0.3",
  operations: [{ method: "get", path: "/demandes", operation_id: "lister" }],
  warnings: [],
};
const SUIVI = { slug: "suivi", sens: "sortant", title: "Suivi des demandes", operations: 1, warnings: [] };

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openContracts() {
  renderWorkspaces();
  fireEvent.click(await screen.findByText("Contracts"));
  await screen.findByRole("heading", { name: "OpenAPI contracts — Retrait de colis" });
}

describe("ContractsScreen", () => {
  it("reads the contract, lets the proposed slug be changed, then imports with the chosen direction", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}`]: [
        { status: 200, body: [] },
        { status: 200, body: [SUIVI] },
      ],
      [`POST ${ROUTE}/preview`]: { status: 200, body: PREVIEW },
      [`POST ${ROUTE}`]: { status: 201, body: SUIVI },
    });
    await openContracts();
    fireEvent.click(screen.getByText("Import a contract"));
    fill("OpenAPI contract (YAML or JSON)", YAML);
    fireEvent.click(screen.getByText("Read the contract"));

    expect(await screen.findByLabelText("Slug")).toHaveValue("suivi-des-demandes");
    fill("Slug", "suivi");
    // Pas de sens par défaut : l'import attend un choix explicite.
    expect(screen.getByText("Import to the work branch")).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Outbound — call to a remote service"));
    fireEvent.click(screen.getByText("Import to the work branch"));

    expect(await screen.findByText("contracts/suivi")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${ROUTE}`)?.body).toEqual({
      slug: "suivi",
      sens: "sortant",
      content: YAML,
    });
  });

  it("flags a contract without operation, and names the occupant of a taken slug", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}`]: { status: 200, body: [] },
      [`POST ${ROUTE}/preview`]: { status: 200, body: { ...PREVIEW, operations: [], warnings: ["aucune_operation"] } },
      [`POST ${ROUTE}`]: { status: 409, body: { detail: { code: "slug_pris", by: "Matériel" } } },
    });
    await openContracts();
    fireEvent.click(screen.getByText("Import a contract"));
    fill("OpenAPI contract (YAML or JSON)", YAML);
    fireEvent.click(screen.getByText("Read the contract"));

    expect(await screen.findByText(/has no operation/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Inbound — webhook received"));
    fireEvent.click(screen.getByText("Import to the work branch"));
    expect(await screen.findByText("This slug is already used by the contract “Matériel”.")).toBeInTheDocument();
  });

  it("names the unsupported version and the accepted ones", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}`]: { status: 200, body: [] },
      [`POST ${ROUTE}/preview`]: {
        status: 422,
        body: { detail: { code: "version_non_prise_en_charge", found: "2.0", accepted: ["3.0", "3.1"] } },
      },
    });
    await openContracts();
    fireEvent.click(screen.getByText("Import a contract"));
    fill("OpenAPI contract (YAML or JSON)", "swagger: '2.0'");
    fireEvent.click(screen.getByText("Read the contract"));

    expect(
      await screen.findByText("OpenAPI version 2.0 is not supported. Accepted: 3.0, 3.1."),
    ).toBeInTheDocument();
  });

  it("lists contracts with their direction and shows their operations, without any rename", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}`]: { status: 200, body: [SUIVI] },
      [`GET ${ROUTE}/suivi`]: {
        status: 200,
        body: { ...SUIVI, operation_list: PREVIEW.operations },
      },
    });
    await openContracts();
    const row = (await screen.findByText("Suivi des demandes")).closest("li") as HTMLElement;
    expect(within(row).getByText("Outbound — call to a remote service")).toBeInTheDocument();
    expect(within(row).queryByText(/rename/i)).not.toBeInTheDocument();

    fireEvent.click(within(row).getByRole("button", { name: "Operations" }));

    expect(await within(row).findByText("GET /demandes — lister")).toBeInTheDocument();
  });
});
