import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import type { Routes } from "@miles/socle-web/testing";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, SETTINGS, renderWorkspaces } from "./workspaceFixtures";

// Prise de main d'une branche enfant (story 9def0adc) : une personne par branche, les
// autres lisent ce qui est publié sans rien pouvoir modifier.
const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const WS = "/api/workspaces/retrait";
const HOLD = `${WS}/branches/edition/hold`;
const BRANCHES = [
  { slug: "atelier", label: "atelier", branch: "back/retrait/atelier", base: true },
  { slug: "edition", label: "Édition", branch: "back/retrait/edition", base: false },
];
const MINE = { slug: "edition", holder: "Gael (gael)", mine: true, taken_at: "2026-10-23T08:00:00Z" };
const BOBS = { ...MINE, holder: "Bob Martin (bob)", mine: false };

afterEach(() => {
  vi.unstubAllGlobals();
});

/** La prise de main vit dans le paramétrage depuis le 24/10/2026 : on l'ouvre d'abord. */
async function onSettings(viewed: string, routes: Routes) {
  const calls = mockApi({
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    "GET /api/branch-views": { status: 200, body: { retrait: viewed } },
    [`GET ${WS}/branches`]: { status: 200, body: BRANCHES },
    ...SETTINGS,
    ...routes,
  });
  renderWorkspaces();
  fireEvent.click(await screen.findByRole("button", { name: "Retrait de colis" }));
  return calls;
}

describe("taking over a branch", () => {
  it("offers to take a free branch, then to publish and release it", async () => {
    const calls = await onSettings("edition", {
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
    expect(await screen.findByText("2 changes published.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Release" })).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toContain(`POST ${HOLD}`);
    expect(calls.map((c) => c.key)).toContain(`POST ${HOLD}/publish`);
  });

  it("names who holds the branch and offers nothing else", async () => {
    await onSettings("edition", { [`GET ${WS}/holds`]: { status: 200, body: [BOBS] } });

    expect(await screen.findByText("Held by Bob Martin (bob)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Take over" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Publish" })).toBeNull();
  });

  it("sends to the profile when no personal git token is registered", async () => {
    await onSettings("edition", {
      [`GET ${WS}/holds`]: { status: 200, body: [] },
      [`POST ${HOLD}`]: { status: 409, body: { detail: "identite_git_requise" } },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Take over" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("in “My profile”");
  });

  it("names the branch already held elsewhere", async () => {
    await onSettings("edition", {
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
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      "GET /api/branch-views": { status: 200, body: { retrait: "atelier" } },
      [`GET ${WS}/branches`]: { status: 200, body: BRANCHES },
      ...SETTINGS,
    });
    renderWorkspaces();

    // La branche affichée se choisit toujours depuis la ligne ; le reste a déménagé.
    expect(await screen.findByText("Branch viewed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retrait de colis" }));

    expect(screen.queryByRole("button", { name: "Take over" })).toBeNull();
    expect(screen.queryByText("Holder")).toBeNull();
  });
});

describe("unlocking and resuming (story fd1eb7da)", () => {
  const SHELF = {
    workspace_id: "retrait",
    workspace_name: "Retrait de colis",
    slug: "edition",
    shelf_branch: "shelve/bob/edition",
    mine: false,
    shelved_at: "2026-10-23T09:00:00Z",
  };

  it("unlocks the holder only after confirmation, then says where the work went", async () => {
    const calls = await onSettings("edition", {
      [`GET ${WS}/holds`]: [
        { status: 200, body: [BOBS] },
        { status: 200, body: [] },
      ],
      [`GET ${WS}/shelves`]: { status: 200, body: [] },
      [`POST ${HOLD}/unlock`]: { status: 200, body: { shelf: SHELF } },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Unlock" }));
    expect(calls.some((c) => c.key === `POST ${HOLD}/unlock`)).toBe(false);
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Unlock" }));

    expect(
      await screen.findByText(/the unpublished work is shelved on shelve\/bob\/edition/),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.key === `POST ${HOLD}/unlock`)).toBe(true);
  });

  it("keeps the branch held and asks for a new token when the forge refuses it", async () => {
    await onSettings("edition", {
      [`GET ${WS}/holds`]: { status: 200, body: [BOBS] },
      [`GET ${WS}/shelves`]: { status: 200, body: [] },
      [`POST ${HOLD}/unlock`]: { status: 409, body: { detail: "jeton_personnel_refuse" } },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Unlock" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Unlock" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("renew their token");
    expect(screen.getByText("Held by Bob Martin (bob)")).toBeInTheDocument();
  });

  it("offers to take over again when my work is shelved, and names conflicting files", async () => {
    await onSettings("edition", {
      [`GET ${WS}/holds`]: { status: 200, body: [] },
      [`GET ${WS}/shelves`]: { status: 200, body: [{ ...SHELF, mine: true }] },
      [`POST ${HOLD}`]: {
        status: 409,
        body: { detail: { code: "conflit_de_reprise", files: ["shared/messages/personne.yaml"] } },
      },
    });

    expect(await screen.findByRole("note")).toHaveTextContent("You have work shelved");
    fireEvent.click(await screen.findByRole("button", { name: "Take over again" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "conflicts with the up-to-date branch (shared/messages/personne.yaml)",
    );
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
