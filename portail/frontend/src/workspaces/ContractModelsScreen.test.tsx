import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { WorkspaceViews } from "../layout/WorkspaceViews";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, renderWorkspaces } from "./workspaceFixtures";

// Modèles dérivés des contrats (story 47f55d8b) : listés par sens, contrat et version,
// ouverts en lecture seule, redérivés quand ils ne disent plus ce que dit le contrat.
const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/contracts";
const Q = "?branch=edition";
const VERSION = {
  number: 1,
  title: "Matériel",
  operations: 1,
  warnings: [],
  imported_at: null,
  imported_by: null,
  models: ["pickup-point", "statut"],
  models_state: "a_jour",
};
const MATERIEL = { slug: "materiel", label: "Matériel", sens: "externe", versions: [VERSION] };
const WEBHOOK = { slug: "retours", label: "Retours", sens: "interne", versions: [] };
const POINT = [
  "$schema: https://json-schema.org/draft/2020-12/schema",
  "$id: miles:/contracts/materiel/v1/pickup-point",
  "title: PickupPoint",
  "type: object",
  "properties:",
  "  statut:",
  "    $ref: miles:/contracts/materiel/v1/statut",
  "",
].join("\n");

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ContractModelsScreen", () => {
  it("lists the models of the external contracts only, by contract and version, and opens one read-only", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [MATERIEL, WEBHOOK] },
      [`GET ${ROUTE}/materiel/versions/1/models/pickup-point${Q}`]: {
        status: 200,
        body: { name: "pickup-point", path: "contracts/materiel/models/v1/pickup-point.yaml", content: POINT },
      },
    });
    renderWorkspaces({ id: "retrait", view: "contractModels", branch: "edition", sens: "externe" });

    // D'abord les contrats du sens choisi (story a3988aaf), puis les modèles de l'un.
    const row = (await screen.findByRole("button", { name: "Matériel" })).closest("li") as HTMLElement;
    expect(within(row).getByText("contracts/materiel")).toBeInTheDocument();
    expect(screen.queryByText("Retours")).toBeNull();
    fireEvent.click(within(row).getByRole("button", { name: "Matériel" }));
    const section = await screen.findByRole("region", { name: "Matériel v1" });
    expect(screen.getByRole("heading", { name: "Models of contract “Matériel”" })).toBeInTheDocument();
    expect(within(section).getByText("contracts/materiel/models/v1/statut.yaml")).toBeInTheDocument();
    // À jour : rien à redériver.
    expect(screen.queryByRole("button", { name: "Derive the models again" })).toBeNull();
    fireEvent.click(within(section).getByRole("button", { name: "pickup-point" }));

    expect(await screen.findByRole("heading", { name: "PickupPoint" })).toBeInTheDocument();
    expect(screen.getByText(/derived from contract materiel, version 1/)).toBeInTheDocument();
    expect(await screen.findByLabelText("YAML", {}, { timeout: 10_000 })).toHaveAttribute("readonly");
    // Lecture seule même avec la main : pas d'« Enregistrer ».
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    // Retour : les modèles du contrat, puis la liste des contrats.
    fireEvent.click(screen.getByRole("button", { name: "← Back to the contract models" }));
    expect(await screen.findByRole("region", { name: "Matériel v1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "← Back to the contracts" }));
    expect(await screen.findByRole("button", { name: "Matériel" })).toBeInTheDocument();
  });

  it("offers to derive stale models again, with the hold, and says when nothing changed", async () => {
    const stale = { ...MATERIEL, versions: [{ ...VERSION, models_state: "a_rederiver", models: [] }] };
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}${Q}`]: [
        { status: 200, body: [stale] },
        { status: 200, body: [MATERIEL] },
      ],
      [`POST ${ROUTE}/materiel/versions/1/models${Q}`]: { status: 200, body: VERSION },
    });
    renderWorkspaces({
      id: "retrait",
      view: "contractModels",
      branch: "edition",
      sens: "externe",
      contract: "materiel",
    });

    expect(await screen.findByText(/no longer match the contract file/)).toBeInTheDocument();
    expect(screen.getByText("This version declares no schema (components/schemas).")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Derive the models again" }));

    expect(await screen.findByRole("button", { name: "pickup-point" })).toBeInTheDocument();
    expect(calls.some((c) => c.key === `POST ${ROUTE}/materiel/versions/1/models${Q}`)).toBe(true);
    expect(screen.queryByText(/no longer match the contract file/)).toBeNull();
  });

  it("offers no rederivation without the hold", async () => {
    const stale = { ...MATERIEL, versions: [{ ...VERSION, models_state: "a_rederiver" }] };
    mockApi({
      "GET /api/workspaces/retrait/holds": { status: 200, body: [] },
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [stale] },
    });
    renderWorkspaces({
      id: "retrait",
      view: "contractModels",
      branch: "edition",
      sens: "externe",
      contract: "materiel",
    });

    expect(await screen.findByText(/no longer match the contract file/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Derive the models again" })).toBeNull();
  });

  it("is reached from two entries under Data models, one per direction", () => {
    const onSelect = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <WorkspaceViews
          workspaceId="retrait"
          branch="edition"
          open={false}
          active
          selection={null}
          onSelect={onSelect}
        />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Internal contracts" }));
    fireEvent.click(screen.getByRole("button", { name: "External contracts" }));

    expect(onSelect.mock.calls).toEqual([
      [{ id: "retrait", view: "contractModels", branch: "edition", sens: "interne" }],
      [{ id: "retrait", view: "contractModels", branch: "edition", sens: "externe" }],
    ]);
  });
});
