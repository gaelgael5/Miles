import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "./App";
import "./i18n/i18n";
import { mockApi } from "./test/mockApi";
import { BARE, CONFIGURED } from "./workspaces/workspaceFixtures";

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

const ADMIN = {
  "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } },
  "GET /api/auth/me": {
    status: 200,
    body: {
      kind: "local_admin",
      username: "admin",
      email: "a@b.c",
      directory: null,
      root_admin: true,
    },
  },
  "GET /api/health": { status: 200, body: {} },
  "GET /api/workspaces": { status: 200, body: [] },
};

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

    expect(await screen.findByRole("button", { name: "OIDC connectors" })).toBeInTheDocument();
    expect(screen.queryByText(/no right/)).not.toBeInTheDocument();
  });

  it("gives the bootstrap administrator the portal navigation", async () => {
    mockApi(ADMIN);

    renderApp();

    const nav = await screen.findByRole("navigation");
    await screen.findByRole("button", { name: "OIDC connectors" });
    // Le menu global d'abord, dans l'ordre voulu, puis les workspaces (21/10/2026).
    expect(Array.from(nav.querySelectorAll(".sidebar-section, .sidebar-link"), (e) => e.textContent)).toEqual([
      "Global",
      "Cultures",
      "Secrets",
      "Git connections",
      "Security services",
      "OIDC connectors",
      "Service status",
      "Workspaces",
      "All workspaces",
    ]);
  });

  it("collapses a main menu, the workspace list being the page shown first", async () => {
    mockApi(ADMIN);
    renderApp();
    const global = await screen.findByRole("button", { name: "Global" });

    fireEvent.click(global);

    expect(global).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "Cultures" })).not.toBeInTheDocument();
    fireEvent.click(global);
    expect(screen.getByRole("button", { name: "Cultures" })).toBeVisible();
    expect(screen.getByRole("button", { name: "All workspaces" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("lists each workspace under Workspaces, whose sub-menu opens its views", async () => {
    mockApi({
      ...ADMIN,
      "GET /api/workspaces": {
        status: 200,
        body: [
          { ...CONFIGURED, work_branch: "work/atelier" },
          { ...BARE, id: "caisse", name: "Caisse" },
        ],
      },
      "GET /api/workspaces/retrait/data-models": { status: 200, body: [] },
      "GET /api/workspaces/retrait/versions": { status: 200, body: [] },
    });
    renderApp();
    const nav = await screen.findByRole("navigation");
    const retrait = await within(nav).findByRole("button", { name: "Retrait de colis" });
    // Replié par défaut : avec beaucoup de workspaces, tout déplier noierait le menu.
    expect(retrait).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(retrait);

    expect(within(nav).getAllByRole("button", { name: "Data models" })).toHaveLength(1);
    // Le paramétrage s'ouvre depuis « Tous les workspaces », pas depuis le menu.
    expect(within(nav).queryByRole("button", { name: "Settings" })).not.toBeInTheDocument();
    // Sans branche de travail, rien à déplier : le nom ouvre le paramétrage du workspace.
    const caisse = within(nav).getByRole("button", { name: "Caisse" });
    expect(caisse).not.toHaveAttribute("aria-expanded");
    fireEvent.click(caisse);
    expect(await screen.findByRole("heading", { name: /Caisse/ })).toBeInTheDocument();
    expect(caisse).toHaveAttribute("aria-current", "page");
    fireEvent.click(within(nav).getByRole("button", { name: "Data models" }));
    expect(
      await screen.findByRole("heading", { name: "Data models — Retrait de colis" }),
    ).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: "Data models" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // Le retour de l'écran ramène aussi le menu sur la liste.
    fireEvent.click(screen.getByText("← Back to workspaces"));
    expect(within(nav).getByRole("button", { name: "All workspaces" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("lists the declared contracts under their workspace, and opens one from the menu", async () => {
    const declared = { slug: "suivi", label: "Suivi des demandes", sens: "sortant", versions: [] };
    mockApi({
      ...ADMIN,
      "GET /api/workspaces": { status: 200, body: [{ ...CONFIGURED, work_branch: "work/atelier" }] },
      "GET /api/workspaces/retrait/contracts": { status: 200, body: [declared] },
      "GET /api/workspaces/retrait/contracts/suivi": { status: 200, body: declared },
    });
    renderApp();
    const nav = await screen.findByRole("navigation");
    fireEvent.click(await within(nav).findByRole("button", { name: "Retrait de colis" }));

    const contract = await within(nav).findByRole("button", { name: "Suivi des demandes" });
    fireEvent.click(contract);

    expect(await screen.findByRole("heading", { name: "Suivi des demandes" })).toBeInTheDocument();
    expect(contract).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("button", { name: "Contracts" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});
