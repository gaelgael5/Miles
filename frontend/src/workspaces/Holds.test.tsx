import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import type { Routes } from "../test/mockApi";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, renderWorkspaces } from "./workspaceFixtures";

// Prise de main d'une branche enfant (story 9def0adc) : une personne par branche, les
// autres lisent ce qui est publié sans rien pouvoir modifier.
const WORKING = { ...CONFIGURED, work_branch: "work/atelier" };
const WS = "/api/workspaces/retrait";
const HOLD = `${WS}/branches/edition/hold`;
const BRANCHES = [
  { slug: "atelier", label: "atelier", branch: "work/atelier", base: true },
  { slug: "edition", label: "Édition", branch: "work/edition", base: false },
];
const MINE = { slug: "edition", holder: "Gael (gael)", mine: true, taken_at: "2026-10-23T08:00:00Z" };
const BOBS = { ...MINE, holder: "Bob Martin (bob)", mine: false };

afterEach(() => {
  vi.unstubAllGlobals();
});

function onList(viewed: string, routes: Routes) {
  const calls = mockApi({
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    "GET /api/branch-views": { status: 200, body: { retrait: viewed } },
    [`GET ${WS}/branches`]: { status: 200, body: BRANCHES },
    ...routes,
  });
  renderWorkspaces();
  return calls;
}

describe("taking over a branch", () => {
  it("offers to take a free branch, then to publish and release it", async () => {
    const calls = onList("edition", {
      [`GET ${WS}/holds`]: [
        { status: 200, body: [] },
        { status: 200, body: [MINE] },
      ],
      [`POST ${HOLD}`]: { status: 201, body: MINE },
      [`GET ${HOLD}`]: { status: 200, body: { hold: MINE, unpublished: 2 } },
      [`POST ${HOLD}/publish`]: { status: 200, body: { published: 2 } },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Take over" }));

    expect(await screen.findByText("You hold this branch")).toBeInTheDocument();
    expect(await screen.findByText(/2 unpublished changes/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByRole("status")).toHaveTextContent("2 changes published.");
    expect(screen.getByRole("button", { name: "Release" })).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toContain(`POST ${HOLD}`);
    expect(calls.map((c) => c.key)).toContain(`POST ${HOLD}/publish`);
  });

  it("names who holds the branch and offers nothing else", async () => {
    onList("edition", { [`GET ${WS}/holds`]: { status: 200, body: [BOBS] } });

    expect(await screen.findByText("Held by Bob Martin (bob)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Take over" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Publish" })).toBeNull();
  });

  it("sends to the profile when no personal git token is registered", async () => {
    onList("edition", {
      [`GET ${WS}/holds`]: { status: 200, body: [] },
      [`POST ${HOLD}`]: { status: 409, body: { detail: "identite_git_requise" } },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Take over" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("in “My profile”");
  });

  it("names the branch already held elsewhere", async () => {
    onList("edition", {
      [`GET ${WS}/holds`]: { status: 200, body: [] },
      [`POST ${HOLD}`]: {
        status: 409,
        body: { detail: { code: "deja_une_branche", workspace_id: "caisse", branch: "essai" } },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Take over" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You already hold branch essai of workspace caisse",
    );
  });

  it("offers no takeover on the read-only root", async () => {
    onList("atelier", {});

    expect(await screen.findByText("Branch viewed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Take over" })).toBeNull();
    expect(screen.queryByText("Holder")).toBeNull();
  });
});

describe("a child branch someone else holds", () => {
  it("reads the models without offering any change, and says who holds it", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${WS}/holds`]: { status: 200, body: [BOBS] },
      [`GET ${WS}/data-models?branch=edition`]: {
        status: 200,
        body: [{ scope: "shared", name: "personne", path: "shared/messages/personne.yaml" }],
      },
      [`GET ${WS}/versions?branch=edition`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "dataModels", branch: "edition" });

    expect(await screen.findByText("personne")).toBeInTheDocument();
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("Bob Martin (bob) holds this branch");
    expect(screen.queryByText("Add a model")).toBeNull();
    expect(screen.queryByText("Delete")).toBeNull();
  });

  it("does not offer to save a version without the hold", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${WS}/holds`]: { status: 200, body: [] },
      [`GET ${WS}/versions?branch=edition`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "branch", branch: "edition" });

    const note = await screen.findByRole("note");
    expect(within(note).getByText(/Nobody holds this branch/)).toBeInTheDocument();
    expect(await screen.findByText(/No version/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save a version" })).toBeNull();
  });
});
