import { fireEvent, screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import {
  BARE,
  CONFIGURED,
  CONNECTION,
  REPORT,
  SETTINGS,
  fill,
  renderWorkspaces as renderScreen,
} from "./workspaceFixtures";

async function openSettings() {
  fireEvent.click(await screen.findByText("Settings"));
  await screen.findByRole("option", { name: /GitHub Acme/ });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkspaceSettings", () => {
  it("records the repository through a connection, announcing the verification branch", async () => {
    const calls = mockApi({
      "GET /api/workspaces": [
        { status: 200, body: [BARE] },
        { status: 200, body: [CONFIGURED] },
      ],
      "PUT /api/workspaces/retrait/repository": { status: 200, body: CONFIGURED },
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();
    expect(screen.getByText(/Save a repository first/)).toBeInTheDocument();
    expect(screen.queryByText("Open the work branch")).not.toBeInTheDocument();

    fill("Git connection", "acme");
    fill("Repository", "https://github.com/acme/retrait");
    const announced = screen.getByText(/creates the branch and tag miles-verification-[0-9a-f]{8}/);
    const suffix = /miles-verification-([0-9a-f]{8})/.exec(announced.textContent ?? "")?.[1];
    fireEvent.click(screen.getByText("Test access and save"));

    expect(await screen.findByText(/Repository saved: https:\/\/github.com\/acme\/retrait.git/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === "PUT /api/workspaces/retrait/repository")?.body).toEqual({
      git_connection_id: "acme",
      repo_url: "https://github.com/acme/retrait",
      verification_suffix: suffix,
    });
    expect(screen.getByText("Open the work branch")).toBeInTheDocument();
  });

  it("names the failed right and the branch left behind, recording nothing", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [BARE] },
      "PUT /api/workspaces/retrait/repository": {
        status: 422,
        body: { detail: { code: "acces_insuffisant", right: "supprimer_branche", reason: "droit_refuse", report: REPORT } },
      },
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();
    fill("Git connection", "acme");
    fill("Repository", "https://github.com/acme/retrait");

    fireEvent.click(screen.getByText("Test access and save"));

    expect(await screen.findByText(/nothing was saved/)).toBeInTheDocument();
    expect(screen.getByText(/Delete a branch — refused: the token has no write right/)).toBeInTheDocument();
    expect(screen.getByText(/miles-verification-0a1b2c3d could not be removed/)).toBeInTheDocument();
  });

  it("says when the repository is outside the connection address", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [BARE] },
      "PUT /api/workspaces/retrait/repository": {
        status: 422,
        body: { detail: { field: "repo_url", reason: "hors_connexion" } },
      },
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();
    fill("Git connection", "acme");
    fill("Repository", "https://github.com/autre/retrait");

    fireEvent.click(screen.getByText("Test access and save"));

    expect(await screen.findByRole("alert")).toHaveTextContent("not under the chosen connection");
  });

  it("locks the repository once a work branch is open", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [{ ...CONFIGURED, work_branch: "work/atelier" }] },
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();

    expect(screen.getByText(/can no longer change/)).toBeInTheDocument();
    expect(screen.getByLabelText("Repository")).toBeDisabled();
    expect(screen.queryByText("Test access and save")).not.toBeInTheDocument();
  });

  it("rechecks access from the settings", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [CONFIGURED] },
      "POST /api/workspaces/retrait/access-check": { status: 200, body: REPORT },
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();

    fireEvent.click(screen.getByText("Test access again"));

    expect(await screen.findByText(/could not be removed/)).toBeInTheDocument();
    const body = calls.find((c) => c.key === "POST /api/workspaces/retrait/access-check")?.body as {
      verification_suffix: string;
    };
    expect(body.verification_suffix).toMatch(/^[0-9a-f]{8}$/);
  });

  it("sets the security service from the settings", async () => {
    const service = {
      id: "racine",
      kind: "keycloak",
      base_url: "https://security.example.org",
      realm: "miles",
      client_id: "miles",
      client_secret_slug: "kc",
      last_check_outcome: "ok",
      last_check_at: null,
      dependent_installations: 0,
    };
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [BARE] },
      "GET /api/git-connections": { status: 200, body: [CONNECTION] },
      "GET /api/security-services": { status: 200, body: [service] },
      "PUT /api/workspaces/retrait/security-service": {
        status: 200,
        body: { ...BARE, security_service_id: "racine" },
      },
    });
    renderScreen();
    await openSettings();
    await screen.findByRole("option", { name: /racine/ });

    fill("Root security service", "racine");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "PUT /api/workspaces/retrait/security-service")?.body).toEqual({
      security_service_id: "racine",
    });
  });
});

describe("WorkBranchPanel", () => {
  it("opens the work branch from the settings", async () => {
    const calls = mockApi({
      "GET /api/workspaces": [
        { status: 200, body: [CONFIGURED] },
        { status: 200, body: [{ ...CONFIGURED, work_branch: "work/atelier" }] },
      ],
      "POST /api/workspaces/retrait/work-branch": {
        status: 201,
        body: { workspace: { ...CONFIGURED, work_branch: "work/atelier" }, outcome: "initialisee" },
      },
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();

    fireEvent.click(screen.getByText("Open the work branch"));

    expect(await screen.findByText("Work branch: work/atelier")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/workspaces/retrait/work-branch")?.body).toEqual({
      name: "atelier",
    });
  });

  it("lists what does not conform and changes nothing", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [CONFIGURED] },
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
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();

    fireEvent.click(screen.getByText("Open the work branch"));

    expect(await screen.findByText(/nothing was changed/)).toBeInTheDocument();
    expect(screen.getByText("manifest.json is missing.")).toBeInTheDocument();
    expect(screen.getByText(/prod\/ looks like an environment folder/)).toBeInTheDocument();
    expect(screen.getByText("Unexpected: src/app.py")).toBeInTheDocument();
  });
});
