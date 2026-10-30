import { fireEvent, screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { BARE, CONFIGURED, SETTINGS, fill, renderWorkspaces as renderScreen } from "./workspaceFixtures";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkspacesScreen", () => {
  it("creates a workspace by its name alone, the identifier following the name", async () => {
    const calls = mockApi({
      "GET /api/workspaces": [
        { status: 200, body: [] },
        { status: 200, body: [BARE] },
      ],
      "POST /api/workspaces": { status: 201, body: BARE },
      ...SETTINGS,
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Create a workspace"));

    const form = screen.getByRole("form", { name: "New workspace" });
    // Nom, identifiant et le filtre du sélecteur de culture : la culture se choisit en
    // cliquant la liste, qui n'est pas un champ de formulaire (Gael, 30/10/2026).
    expect(form.querySelectorAll("input, select, textarea")).toHaveLength(3);
    fill("Name", "Caisse Été");
    expect(screen.getByLabelText("Identifier")).toHaveValue("caisse-ete");
    fill("Identifier", "retrait");
    fill("Name", "Retrait de colis");
    expect(screen.getByLabelText("Identifier")).toHaveValue("retrait");
    // L'option, pas seulement le champ : le catalogue se charge après le rendu, et une
    // valeur sans option correspondante est un geste sans effet (LESSONS.md).
    fireEvent.click(await screen.findByRole("button", { name: /fr-FR/ }));
    fireEvent.click(screen.getByText("Create the workspace"));

    // Juste créé, il n'a pas de dépôt : on enchaîne sur son paramétrage.
    expect(await screen.findByText("Settings — Retrait de colis")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/workspaces")?.body).toEqual({
      id: "retrait",
      name: "Retrait de colis",
      default_culture: "fr-FR",
    });
  });

  it("cannot create a workspace before a default culture is chosen", async () => {
    mockApi({ "GET /api/workspaces": { status: 200, body: [] }, ...SETTINGS });
    renderScreen();
    fireEvent.click(await screen.findByText("Create a workspace"));
    fill("Name", "Retrait de colis");

    expect(screen.getByText("Create the workspace")).toBeDisabled();

    fireEvent.click(await screen.findByRole("button", { name: /th-TH/ }));

    expect(screen.getByText("Create the workspace")).toBeEnabled();
  });

  it("offers the whole catalogue, not only the cultures the application displays", async () => {
    // Traduire en thaï n'exige pas de lire le back-office en thaï (critère 9).
    mockApi({ "GET /api/workspaces": { status: 200, body: [] }, ...SETTINGS });
    renderScreen();
    fireEvent.click(await screen.findByText("Create a workspace"));

    expect(await screen.findByRole("button", { name: /th-TH/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ar-MA/ })).toBeInTheDocument();
  });

  it("says when the identifier is already taken", async () => {
    mockApi({
      "GET /api/workspaces": { status: 200, body: [] },
      "POST /api/workspaces": { status: 409, body: { detail: "identifiant_pris" } },
      ...SETTINGS,
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Create a workspace"));
    fill("Name", "Retrait");
    fireEvent.click(await screen.findByRole("button", { name: /fr-FR/ }));

    fireEvent.click(screen.getByText("Create the workspace"));

    expect(await screen.findByRole("alert")).toHaveTextContent("already used by another workspace");
  });

  it("flags a workspace whose repository is still to set up", async () => {
    mockApi({ "GET /api/workspaces": { status: 200, body: [BARE, { ...CONFIGURED, id: "caisse" }] } });
    renderScreen();

    expect(await screen.findByText("Repository to set up")).toBeInTheDocument();
    expect(screen.getByText("https://github.com/acme/retrait.git")).toBeInTheDocument();
  });
});
