import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { WorkspacesScreen } from "./WorkspacesScreen";

const SECRETS = "GET /api/secrets?secret_type=GIT_TOKEN";
const TOKEN = {
  slug: "gh",
  label: "Jeton GitHub",
  secret_type: "GIT_TOKEN",
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:00:00Z",
  consumers: [],
};
const REPORT = {
  branch: "miles-verification-0a1b2c3d",
  tag: "miles-verification-0a1b2c3d",
  checks: [
    { right: "lire", ok: true, reason: null },
    { right: "creer_branche", ok: true, reason: null },
    { right: "pousser", ok: true, reason: null },
    { right: "poser_tag", ok: true, reason: null },
    { right: "supprimer_branche", ok: false, reason: "droit_refuse" },
  ],
  residual_branch: "miles-verification-0a1b2c3d",
  residual_tag: null,
  existing_branches: 0,
  initialized_branch: "main",
  all_passed: false,
};
const WORKSPACE = {
  id: "retrait",
  name: "Retrait de colis",
  repo_url: "https://github.com/acme/retrait.git",
  git_secret_slug: "gh",
  security_service_id: null,
  last_check: { ...REPORT, all_passed: true, residual_branch: null, checks: REPORT.checks.map((c) => ({ ...c, ok: true, reason: null })) },
  last_check_at: "2026-10-20T10:00:00Z",
  created_at: "2026-10-20T10:00:00Z",
  work_branch: null,
};

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WorkspacesScreen />
    </QueryClientProvider>,
  );
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

async function fillForm() {
  fireEvent.click(await screen.findByText("Create a workspace"));
  fill("Identifier", "retrait");
  fill("Name", "Retrait de colis");
  fill("GitHub repository", "https://github.com/acme/retrait");
  await screen.findByRole("option", { name: "Jeton GitHub" });
  fill("Repository access token", "gh");
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkspacesScreen", () => {
  it("creates a workspace, announcing the verification branch before the test", async () => {
    const calls = mockApi({
      "GET /api/workspaces": [
        { status: 200, body: [] },
        { status: 200, body: [WORKSPACE] },
      ],
      [SECRETS]: { status: 200, body: [TOKEN] },
      "GET /api/security-services": { status: 200, body: [] },
      "POST /api/workspaces": { status: 201, body: WORKSPACE },
    });
    renderScreen();
    await fillForm();

    const announced = screen.getByText(/creates the branch and tag miles-verification-[0-9a-f]{8}/);
    const suffix = /miles-verification-([0-9a-f]{8})/.exec(announced.textContent ?? "")?.[1];
    fireEvent.click(screen.getByText("Test access and create"));

    expect(await screen.findByText("Retrait de colis")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/workspaces")?.body).toEqual({
      id: "retrait",
      name: "Retrait de colis",
      repo_url: "https://github.com/acme/retrait",
      git_secret_slug: "gh",
      security_service_id: null,
      verification_suffix: suffix,
    });
    expect(screen.getByText(/No root security service referenced/)).toBeInTheDocument();
  });

  it("names the failed right and the branch left behind", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [] },
      [SECRETS]: { status: 200, body: [TOKEN] },
      "GET /api/security-services": { status: 200, body: [] },
      "POST /api/workspaces": {
        status: 422,
        body: { detail: { code: "acces_insuffisant", right: "supprimer_branche", reason: "droit_refuse", report: REPORT } },
      },
    });
    renderScreen();
    await fillForm();

    fireEvent.click(screen.getByText("Test access and create"));

    expect(await screen.findByText(/the workspace was not created/)).toBeInTheDocument();
    expect(screen.getByText(/Delete a branch — refused: the token has no write right/)).toBeInTheDocument();
    expect(
      screen.getByText("The branch miles-verification-0a1b2c3d could not be removed: delete it by hand, then test again."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Miles created the branch main/)).toBeInTheDocument();
  });

  it("says when the repository already belongs to another workspace", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [] },
      [SECRETS]: { status: 200, body: [TOKEN] },
      "GET /api/security-services": { status: 200, body: [] },
      "POST /api/workspaces": { status: 409, body: { detail: "depot_deja_associe" } },
    });
    renderScreen();
    await fillForm();

    fireEvent.click(screen.getByText("Test access and create"));

    expect(await screen.findByRole("alert")).toHaveTextContent("already belongs to another workspace");
  });

  it("rechecks access from the workspace card", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKSPACE] },
      "POST /api/workspaces/retrait/access-check": { status: 200, body: REPORT },
    });
    renderScreen();

    fireEvent.click(await screen.findByText("Test access again"));

    expect(await screen.findByText(/could not be removed/)).toBeInTheDocument();
    const body = calls.find((c) => c.key === "POST /api/workspaces/retrait/access-check")?.body as {
      verification_suffix: string;
    };
    expect(body.verification_suffix).toMatch(/^[0-9a-f]{8}$/);
  });
});

describe("WorkBranchPanel", () => {
  it("opens the work branch from the workspace card", async () => {
    const calls = mockApi({
      "GET /api/workspaces": [
        { status: 200, body: [WORKSPACE] },
        { status: 200, body: [{ ...WORKSPACE, work_branch: "work/atelier" }] },
      ],
      "POST /api/workspaces/retrait/work-branch": {
        status: 201,
        body: { workspace: { ...WORKSPACE, work_branch: "work/atelier" }, outcome: "initialisee" },
      },
    });
    renderScreen();

    fireEvent.click(await screen.findByText("Open the work branch"));

    expect(await screen.findByText("Work branch: work/atelier")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/workspaces/retrait/work-branch")?.body).toEqual({
      name: "atelier",
    });
  });

  it("lists what does not conform and changes nothing", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKSPACE] },
      "POST /api/workspaces/retrait/work-branch": {
        status: 422,
        body: {
          detail: {
            code: "arborescence_non_conforme",
            unexpected: ["src/app.py"],
            environment_dirs: ["prod"],
            manifest: "absent",
          },
        },
      },
    });
    renderScreen();

    fireEvent.click(await screen.findByText("Open the work branch"));

    expect(await screen.findByText(/nothing was changed/)).toBeInTheDocument();
    expect(screen.getByText("manifest.json is missing.")).toBeInTheDocument();
    expect(screen.getByText(/prod\/ looks like an environment folder/)).toBeInTheDocument();
    expect(screen.getByText("Unexpected: src/app.py")).toBeInTheDocument();
  });
});
