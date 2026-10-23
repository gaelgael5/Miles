import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { proposeSlug } from "../api/contracts";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "work/atelier" };
const ROUTE = "/api/workspaces/retrait/contracts";
const DECLARED = { slug: "suivi", label: "Suivi des demandes", sens: "sortant", versions: [] };
const V1 = { number: 1, title: "Suivi des demandes", operations: 1, warnings: [] };

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openContracts() {
  // Une branche enfant : la racine est en lecture seule (story dca0eb0e).
  renderWorkspaces({ id: "retrait", view: "contracts", branch: "edition" });
  await screen.findByRole("heading", { name: "OpenAPI contracts — Retrait de colis" });
}

describe("proposeSlug", () => {
  it.each([
    ["Suivi des demandes", "suivi-des-demandes"],
    ["  API Matériel — v2 ", "api-materiel-v2"],
    ["Événements_Colis", "evenements-colis"],
    ["这是", ""],
    ["x".repeat(80), "x".repeat(63)],
  ])("proposes %j as %j", (label, slug) => {
    expect(proposeSlug(label)).toBe(slug);
  });
});

describe("ContractsScreen", () => {
  it("declares a contract with its label, proposed slug and direction, then opens it", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}?branch=edition`]: [
        { status: 200, body: [] },
        { status: 200, body: [DECLARED] },
      ],
      [`POST ${ROUTE}?branch=edition`]: { status: 201, body: DECLARED },
      [`GET ${ROUTE}/suivi?branch=edition`]: { status: 200, body: DECLARED },
    });
    await openContracts();
    fireEvent.click((await screen.findByRole("button", { name: "Declare a contract" })));

    fill("Label", "Suivi des demandes");
    expect(screen.getByLabelText("Slug")).toHaveValue("suivi-des-demandes");
    fill("Slug", "suivi");
    fill("Label", "Suivi des demandes du tiers");
    // Touché à la main, le slug ne suit plus le label.
    expect(screen.getByLabelText("Slug")).toHaveValue("suivi");
    // Pas de sens par défaut : la déclaration attend un choix explicite.
    expect(screen.getByText("Declare the contract")).toBeDisabled();
    fireEvent.click(screen.getByLabelText("External — call to a remote service"));
    fireEvent.click(screen.getByText("Declare the contract"));

    expect(await screen.findByRole("heading", { name: "Suivi des demandes" })).toBeInTheDocument();
    expect(screen.getByText(/No file integrated yet/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${ROUTE}?branch=edition`)?.body).toEqual({
      label: "Suivi des demandes du tiers",
      slug: "suivi",
      sens: "sortant",
    });
  });

  it("names the occupant of a taken slug and the missing label", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}?branch=edition`]: { status: 200, body: [] },
      [`POST ${ROUTE}?branch=edition`]: [
        { status: 409, body: { detail: { code: "slug_pris", by: "Matériel" } } },
        { status: 422, body: { detail: { field: "label", reason: "vide" } } },
      ],
    });
    await openContracts();
    fireEvent.click((await screen.findByRole("button", { name: "Declare a contract" })));
    fill("Label", "Matériel");
    fireEvent.click(screen.getByLabelText("Internal — webhook received"));

    fireEvent.click(screen.getByText("Declare the contract"));
    expect(
      await screen.findByText("This slug is already used by the contract “Matériel”."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("Declare the contract"));
    expect(await screen.findByText("Give the contract a label.")).toBeInTheDocument();
  });

  it("lists contracts with their direction and versions, flagging the ones without file", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}?branch=edition`]: {
        status: 200,
        body: [
          { ...DECLARED, versions: [V1, { ...V1, number: 2 }] },
          { slug: "vide", label: "Sans fichier", sens: "entrant", versions: [] },
        ],
      },
    });
    await openContracts();

    const row = (await screen.findByText("Suivi des demandes")).closest("li") as HTMLElement;
    expect(within(row).getByText("External — call to a remote service")).toBeInTheDocument();
    expect(within(row).getByText("2 versions (latest v2)")).toBeInTheDocument();
    expect(within(row).queryByText(/rename/i)).not.toBeInTheDocument();
    const empty = screen.getByText("Sans fichier").closest("li") as HTMLElement;
    expect(within(empty).getByText("No file yet")).toBeInTheDocument();
  });
});
