import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { BARE, CONFIGURED, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "work/atelier" };
const ROUTE = "/api/workspaces/retrait/branches";
const BASE = { slug: "atelier", label: "atelier", branch: "work/atelier", base: true };
const ESSAI = { slug: "essai-de-gael", label: "Essai de Gaël", branch: "work/essai-de-gael", base: false };

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openForm() {
  renderWorkspaces();
  const row = (await screen.findByText("Retrait de colis")).closest("li") as HTMLElement;
  fireEvent.click(within(row).getByRole("button", { name: "New branch" }));
}

describe("BranchForm", () => {
  it("creates a branch from the base with its label and proposed slug, then opens it", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`POST ${ROUTE}`]: { status: 201, body: ESSAI },
      [`GET ${ROUTE}`]: { status: 200, body: [BASE, ESSAI] },
      "GET /api/workspaces/retrait/versions?branch=essai-de-gael": { status: 200, body: [] },
    });
    await openForm();
    expect(screen.getByText(/head of the base branch work\/atelier/)).toBeInTheDocument();

    fill("Label", "Essai de Gaël");
    expect(screen.getByLabelText("Slug")).toHaveValue("essai-de-gael");
    fireEvent.click(screen.getByText("Create the branch"));

    expect(
      await screen.findByRole("heading", { name: "Retrait de colis — branch essai-de-gael" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("work/essai-de-gael")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${ROUTE}`)?.body).toEqual({
      label: "Essai de Gaël",
      slug: "essai-de-gael",
    });
  });

  it("names the occupant of a taken slug, and the invalid slug", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`POST ${ROUTE}`]: [
        { status: 409, body: { detail: { code: "slug_pris", by: "work/essai" } } },
        { status: 422, body: { detail: { field: "slug" } } },
      ],
    });
    await openForm();
    fill("Label", "Essai");

    fireEvent.click(screen.getByText("Create the branch"));
    expect(
      await screen.findByText("This slug or branch is already taken by “work/essai”."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("Create the branch"));
    expect(await screen.findByText(/Slug: lowercase letters/)).toBeInTheDocument();
  });

  it("is not offered on a workspace without base branch", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [{ ...BARE, id: "caisse", name: "Caisse" }] },
    });
    renderWorkspaces();
    const row = (await screen.findByText("Caisse")).closest("li") as HTMLElement;

    expect(within(row).queryByRole("button", { name: "New branch" })).not.toBeInTheDocument();
  });
});
