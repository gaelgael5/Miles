import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "work/atelier" };
const ROUTE = "/api/workspaces/retrait/contracts";
const YAML = "openapi: 3.1.0\ninfo: {title: Matériel, version: '2'}\npaths: {}\n";
const PREVIEW = { title: "Matériel", openapi: "3.1.0", operations: [], warnings: ["aucune_operation"] };
const OPERATION = { method: "get", path: "/demandes", operation_id: "lister" };
const V1 = {
  number: 1,
  title: "Matériel",
  operations: 1,
  warnings: [],
  imported_at: "2026-10-22T08:00:00Z",
  imported_by: "admin via Miles <admin@local.miles.invalid>",
  operation_list: [{ ...OPERATION, change: null }],
  compared_with: null,
  removed: [],
};
const V2 = {
  ...V1,
  number: 2,
  imported_at: null,
  imported_by: null,
  operation_list: [{ method: "post", path: "/colis", operation_id: "deposer", change: "nouvelle" }],
  compared_with: 1,
  removed: [OPERATION],
};
const DECLARED = { slug: "materiel", label: "Matériel du tiers", sens: "entrant", versions: [] };
const CONTENT = "OpenAPI contract (YAML or JSON)";

afterEach(() => {
  vi.unstubAllGlobals();
});

function routes(extra: Record<string, unknown>) {
  return {
    ...HELD,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    [`GET ${ROUTE}?branch=edition`]: { status: 200, body: [DECLARED] },
    ...extra,
  } as Parameters<typeof mockApi>[0];
}

async function openContract() {
  // Une branche enfant : la racine est en lecture seule (story dca0eb0e).
  renderWorkspaces({ id: "retrait", view: "contracts", branch: "edition" });
  fireEvent.click(await screen.findByRole("button", { name: "Open" }));
  await screen.findByRole("heading", { name: "Matériel du tiers" });
}

describe("ContractScreen", () => {
  it("integrates a pasted file as a new version, after reading it", async () => {
    const calls = mockApi(
      routes({
        [`GET ${ROUTE}/materiel?branch=edition`]: [
          { status: 200, body: DECLARED },
          { status: 200, body: { ...DECLARED, versions: [V1] } },
        ],
        [`POST ${ROUTE}/preview?branch=edition`]: { status: 200, body: PREVIEW },
        [`POST ${ROUTE}/materiel/versions?branch=edition`]: { status: 201, body: V1 },
      }),
    );
    await openContract();

    fill(CONTENT, YAML);
    fireEvent.click(screen.getByText("Read the file"));
    expect(await screen.findByText(/has no operation/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Integrate as a new version"));

    expect(await screen.findByText("Integrated as version v1.")).toBeInTheDocument();
    const row = (await screen.findByText("v1 — Matériel")).closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Operations" }));
    expect(within(row).getByText(/GET \/demandes — lister/)).toBeInTheDocument();
    expect(within(row).getByText(/Deposited on .* by admin via Miles/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${ROUTE}/materiel/versions?branch=edition`)?.body).toEqual({
      content: YAML,
    });
  });

  it("loads a chosen file into the contract text and reads it at once", async () => {
    const calls = mockApi(
      routes({
        [`GET ${ROUTE}/materiel?branch=edition`]: { status: 200, body: DECLARED },
        [`POST ${ROUTE}/preview?branch=edition`]: { status: 200, body: PREVIEW },
      }),
    );
    await openContract();

    const file = new File([YAML], "materiel.yaml", { type: "application/yaml" });
    // jsdom n'a pas Blob.text(), que tous les navigateurs visés fournissent.
    Object.defineProperty(file, "text", { value: () => Promise.resolve(YAML) });
    fireEvent.change(screen.getByLabelText("From a file"), { target: { files: [file] } });

    expect(await screen.findByText("Integrate as a new version")).toBeInTheDocument();
    expect(screen.getByLabelText(CONTENT)).toHaveValue(YAML);
    expect(calls.find((c) => c.key === `POST ${ROUTE}/preview?branch=edition`)?.body).toEqual({ content: YAML });
  });

  it("fetches an address through the back-office, then shows what will be integrated", async () => {
    const calls = mockApi(
      routes({
        [`GET ${ROUTE}/materiel?branch=edition`]: { status: 200, body: DECLARED },
        [`POST ${ROUTE}/fetch?branch=edition`]: { status: 200, body: { content: YAML } },
        [`POST ${ROUTE}/preview?branch=edition`]: { status: 200, body: PREVIEW },
      }),
    );
    await openContract();
    expect(screen.getByText("Fetch")).toBeDisabled();

    fill("From an address", "https://tiers.example/openapi.yaml");
    fireEvent.click(screen.getByText("Fetch"));

    expect(await screen.findByText("Integrate as a new version")).toBeInTheDocument();
    expect(screen.getByLabelText(CONTENT)).toHaveValue(YAML);
    expect(calls.find((c) => c.key === `POST ${ROUTE}/fetch?branch=edition`)?.body).toEqual({
      url: "https://tiers.example/openapi.yaml",
    });
  });

  it("says why an address was not read, without touching the contract text", async () => {
    mockApi(
      routes({
        [`GET ${ROUTE}/materiel?branch=edition`]: { status: 200, body: DECLARED },
        [`POST ${ROUTE}/fetch?branch=edition`]: [
          { status: 422, body: { detail: { code: "lecture_distante", reason: "statut", status: 404 } } },
          { status: 422, body: { detail: { code: "lecture_distante", reason: "adresse_interdite" } } },
        ],
      }),
    );
    await openContract();
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

  it("names the unsupported version and goes back to the contract list", async () => {
    mockApi(
      routes({
        [`GET ${ROUTE}/materiel?branch=edition`]: { status: 200, body: DECLARED },
        [`POST ${ROUTE}/preview?branch=edition`]: {
          status: 422,
          body: { detail: { code: "version_non_prise_en_charge", found: "2.0", accepted: ["3.0", "3.1"] } },
        },
      }),
    );
    await openContract();
    fill(CONTENT, "swagger: '2.0'");
    fireEvent.click(screen.getByText("Read the file"));

    expect(
      await screen.findByText("OpenAPI version 2.0 is not supported. Accepted: 3.0, 3.1."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("Back to contracts"));
    expect(
      await screen.findByRole("heading", { name: "OpenAPI contracts — Retrait de colis" }),
    ).toBeInTheDocument();
  });

  it("shows what a new version adds, what it no longer exposes, and that nothing is mapped yet", async () => {
    mockApi(
      routes({
        [`GET ${ROUTE}/materiel?branch=edition`]: {
          status: 200,
          body: { ...DECLARED, versions: [V1, V2] },
        },
      }),
    );
    await openContract();
    const row = (await screen.findByText("v2 — Matériel")).closest("li") as HTMLElement;
    expect(within(row).getByText("Deposited outside Miles: date unknown")).toBeInTheDocument();

    fireEvent.click(within(row).getByRole("button", { name: "Operations" }));

    const added = within(row).getByText(/POST \/colis — deposer/);
    expect(within(added).getByText("New")).toBeInTheDocument();
    expect(within(added).getByText("Not mapped")).toBeInTheDocument();
    expect(within(row).getByText(/Exposed by v1, no longer by this version/)).toBeInTheDocument();
    expect(within(row).getByText(/GET \/demandes — lister/)).toBeInTheDocument();
  });
});
