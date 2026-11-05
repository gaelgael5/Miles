import { fireEvent, screen } from "@testing-library/react";

import { ADMIN, openMenu, renderApp } from "./appTestHarness";
import { mockApi } from "@miles/socle-web/testing";

/**
 * Qui voit quoi, et ce que le menu montre en arrivant.
 *
 * Réparti par NATURE le 3 novembre 2026 (enabler `82ec7d76`) : les gardes qui portent sur
 * la BRANCHE VUE sont dans `App.branches.test.tsx`.
 */
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("gives an OIDC session without roles nothing but its identity and sign-out", async () => {
    mockApi({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } },
      "GET /api/auth/me": {
        status: 200,
        body: { kind: "oidc", username: "Alice", email: null, directory: "kc", root_admin: false },
      },
    });

    renderApp();

    expect(await screen.findByText(/signed in through kc, but no right/)).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("gives an OIDC session recognised as administrator the full portal", async () => {
    mockApi({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } },
      "GET /api/auth/me": {
        status: 200,
        body: { kind: "oidc", username: "Alice", email: "a@b.c", directory: "kc", root_admin: true },
      },
      "GET /api/health": { status: 200, body: {} },
    });

    renderApp();

    await openMenu("Global");
    expect(screen.getByRole("button", { name: "OIDC connectors" })).toBeInTheDocument();
    expect(screen.queryByText(/no right/)).not.toBeInTheDocument();
  });

  it("collapses the menu from the top bar", async () => {
    // Le bouton est dans la BARRE, le menu dans le corps : deux composants que l'App
    // rend côte à côte, et c'est elle qui les relie. Sans cette garde, un produit peut
    // oublier de poser la classe ou l'identifiant, et le bouton ne commanderait rien.
    mockApi(ADMIN);
    renderApp();
    const replier = await screen.findByRole("button", { name: "Collapse or expand the menu" });
    expect(replier).toHaveAttribute("aria-controls", screen.getByRole("navigation").id);

    fireEvent.click(replier);

    expect(screen.getByRole("navigation")).toHaveClass("sidebar-collapsed");
  });

  it("gives the bootstrap administrator the portal navigation", async () => {
    mockApi(ADMIN);

    renderApp();

    const nav = await screen.findByRole("navigation");
    // Tout est replié au chargement : on ouvre les deux niveaux dont ce test parle.
    await openMenu("Global");
    await openMenu("Globalisation");
    await openMenu("Agent");
    await openMenu("Workspaces");
    // Le menu global d'abord, dans l'ordre voulu, puis les workspaces (21/10/2026).
    expect(Array.from(nav.querySelectorAll(".sidebar-section, .sidebar-link"), (e) => e.textContent)).toEqual([
      "Global",
      // Les trois référentiels DONNÉS sous leur propre sous-groupe repliable, et dans cet
      // ordre : le libellé d'un pays comme d'un fuseau dépend des cultures actives
      // (Gael, 30/10/2026).
      "Globalisation",
      "Cultures",
      "Countries",
      "Time zones",
      "Secrets",
      "Git connections",
      "Pairing",
      "Security services",
      "OIDC connectors",
      // Ce par quoi un agent entre, sous son propre sous-groupe (Gael, 30/10/2026).
      "Agent",
      "API keys",
      "OAuth clients",
      // Le journal d'events, avant l'état du service : les deux se lisent quand on
      // diagnostique, et aucun des deux n'est un réglage (story 50bfcba0).
      "Event journal",
      "Service status",
      "Workspaces",
      "All workspaces",
    ]);
  });

  it("collapses a main menu, the workspace list being the page shown first", async () => {
    mockApi(ADMIN);
    renderApp();
    const global = await screen.findByRole("button", { name: "Global" });

    // Replié d'emblée : rien de son contenu n'est atteignable.
    expect(global).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "Globalisation" })).not.toBeInTheDocument();

    fireEvent.click(global);

    expect(global).toHaveAttribute("aria-expanded", "true");
    await openMenu("Globalisation");
    expect(screen.getByRole("button", { name: "Cultures" })).toBeVisible();
    fireEvent.click(global);
    expect(screen.queryByRole("button", { name: "Cultures" })).not.toBeInTheDocument();
    await openMenu("Workspaces");
    expect(screen.getByRole("button", { name: "All workspaces" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
