import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
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
  // La ligne entière mène au paramétrage : c'est le nom du workspace qui porte le geste.
  fireEvent.click(await screen.findByRole("button", { name: "Retrait de colis" }));
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
      "GET /api/workspaces": { status: 200, body: [{ ...CONFIGURED, work_branch: "back/retrait/atelier" }] },
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

describe("deleting a workspace", () => {
  it("asks for confirmation, then forgets it and returns to the list", async () => {
    const calls = mockApi({
      "GET /api/workspaces": [
        { status: 200, body: [CONFIGURED] },
        { status: 200, body: [] },
      ],
      "DELETE /api/workspaces/retrait": { status: 204, body: undefined },
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();

    fireEvent.click(screen.getByRole("button", { name: "Delete the workspace" }));
    const dialog = await screen.findByRole("dialog");
    // Rien n'est envoyé tant que la confirmation n'est pas donnée.
    expect(calls.some((c) => c.key === "DELETE /api/workspaces/retrait")).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete the workspace" }));

    expect(await screen.findByText("No workspace yet.")).toBeInTheDocument();
    expect(calls.some((c) => c.key === "DELETE /api/workspaces/retrait")).toBe(true);
  });

  it("names who holds a branch instead of losing their unpublished work", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [CONFIGURED] },
      "DELETE /api/workspaces/retrait": {
        status: 409,
        body: { detail: { code: "branche_tenue", by: "Bob Martin (bob)" } },
      },
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();

    fireEvent.click(screen.getByRole("button", { name: "Delete the workspace" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete the workspace" }));

    expect(await screen.findByText(/Bob Martin \(bob\) holds a branch/)).toBeInTheDocument();
  });
});

describe("WorkBranchPanel", () => {
  it("opens the work branch from the settings", async () => {
    const calls = mockApi({
      "GET /api/workspaces": [
        { status: 200, body: [CONFIGURED] },
        { status: 200, body: [{ ...CONFIGURED, work_branch: "back/retrait/root" }] },
      ],
      "POST /api/workspaces/retrait/work-branch": {
        status: 201,
        body: { workspace: { ...CONFIGURED, work_branch: "back/retrait/root" }, outcome: "initialisee" },
      },
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();

    fireEvent.click(screen.getByText("Open the work branch"));

    expect(await screen.findByText("Work branch: back/retrait/root")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/workspaces/retrait/work-branch")?.body).toEqual({
      name: "root",
      adopt_existing: false,
    });
  });

  it("offers to take over a branch that already exists, and takes it over on demand", async () => {
    const calls = mockApi({
      "GET /api/workspaces": [
        { status: 200, body: [CONFIGURED] },
        { status: 200, body: [{ ...CONFIGURED, work_branch: "back/retrait/root" }] },
      ],
      "POST /api/workspaces/retrait/work-branch": [
        { status: 409, body: { detail: "branche_existante" } },
        {
          status: 201,
          body: { workspace: { ...CONFIGURED, work_branch: "back/retrait/root" }, outcome: "reprise" },
        },
      ],
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();

    fireEvent.click(screen.getByText("Open the work branch"));
    // Le refus se rattrape : il propose le geste au lieu d'être un cul-de-sac.
    fireEvent.click(await screen.findByText("Take over this existing branch"));

    expect(await screen.findByText("Work branch: back/retrait/root")).toBeInTheDocument();
    const sent = calls
      .filter((c) => c.key === "POST /api/workspaces/retrait/work-branch")
      .map((c) => c.body);
    expect(sent).toEqual([
      { name: "root", adopt_existing: false },
      { name: "root", adopt_existing: true },
    ]);
  });

  it("stops offering to take over once the branch name is changed", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [CONFIGURED] },
      "POST /api/workspaces/retrait/work-branch": {
        status: 409,
        body: { detail: "branche_existante" },
      },
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();

    fireEvent.click(screen.getByText("Open the work branch"));
    await screen.findByText("Take over this existing branch");
    // Le refus portait sur « root » : il ne vaut pas confirmation pour un autre nom.
    fireEvent.change(screen.getByLabelText(/Work branch name/), {
      target: { value: "autre" },
    });

    expect(screen.queryByText("Take over this existing branch")).not.toBeInTheDocument();
  });

  it("does not offer to take over when the refusal is something else", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [CONFIGURED] },
      "POST /api/workspaces/retrait/work-branch": {
        status: 409,
        body: { detail: "branche_de_travail_existante" },
      },
      ...SETTINGS,
    });
    renderScreen();
    await openSettings();

    fireEvent.click(screen.getByText("Open the work branch"));

    expect(await screen.findByText("This workspace already has a work branch.")).toBeInTheDocument();
    expect(screen.queryByText("Take over this existing branch")).not.toBeInTheDocument();
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
