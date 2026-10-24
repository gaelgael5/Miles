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

const BRANCHES = [
  { slug: "atelier", label: "atelier", branch: "back/retrait/atelier", base: true },
  { slug: "essai", label: "Essai Gael", branch: "back/retrait/essai", base: false },
];

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
      "API keys",
      "OAuth clients",
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

  it("names each workspace after the branch viewed, and opens that branch's views", async () => {
    const calls = mockApi({
      ...ADMIN,
      "GET /api/workspaces": {
        status: 200,
        body: [
          { ...CONFIGURED, work_branch: "back/retrait/atelier" },
          { ...BARE, id: "caisse", name: "Caisse" },
        ],
      },
      "GET /api/branch-views": { status: 200, body: { retrait: "essai" } },
      "GET /api/workspaces/retrait/branches": { status: 200, body: BRANCHES },
      "GET /api/workspaces/retrait/data-models?branch=essai": { status: 200, body: [] },
      "GET /api/workspaces/retrait/contracts?branch=essai": { status: 200, body: [] },
      "GET /api/workspaces/retrait/storages?branch=essai": { status: 200, body: [] },
    });
    renderApp();
    const nav = await screen.findByRole("navigation");
    const retrait = await within(nav).findByRole("button", { name: "Retrait de colis (essai)" });
    // Replié par défaut : avec beaucoup de workspaces, tout déplier noierait le menu.
    expect(retrait).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(retrait);
    // Les branches ne sont pas listées : seules les vues de la branche regardée.
    expect(within(nav).queryByRole("button", { name: "atelier" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("button", { name: "Settings" })).not.toBeInTheDocument();
    // La vue ferroviaire s'atteint d'ici : un écran qu'on ne peut pas ouvrir n'existe
    // pas, et le menu a sa PROPRE liste de vues (relevé par Gael le 24/10/2026).
    expect(within(nav).getByRole("button", { name: "Branches" })).toBeInTheDocument();
    // Même garde pour « Storages » (24/10/2026) : la vue est déclarée dans la liste du
    // menu, pas seulement dans le routage — sans quoi l'écran serait inatteignable.
    fireEvent.click(within(nav).getByRole("button", { name: "Storages" }));
    expect(
      await screen.findByRole("heading", { name: "Storages — Retrait de colis" }),
    ).toBeInTheDocument();
    fireEvent.click(within(nav).getByRole("button", { name: "Data models" }));

    expect(
      await screen.findByRole("heading", { name: "Data models — Retrait de colis" }),
    ).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: "Data models" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(calls.some((c) => c.key.includes("branch=atelier"))).toBe(false);
    // Sans branche de travail, rien à déplier : le nom ouvre le paramétrage du workspace.
    const caisse = within(nav).getByRole("button", { name: "Caisse" });
    expect(caisse).not.toHaveAttribute("aria-expanded");
    fireEvent.click(caisse);
    expect(await screen.findByRole("heading", { name: /Caisse/ })).toBeInTheDocument();
    expect(caisse).toHaveAttribute("aria-current", "page");
  });

  it("switches the branch viewed from All workspaces, which renames the workspace in the menu", async () => {
    const calls = mockApi({
      ...ADMIN,
      "GET /api/workspaces": { status: 200, body: [{ ...CONFIGURED, work_branch: "back/retrait/atelier" }] },
      "GET /api/branch-views": [
        { status: 200, body: {} },
        { status: 200, body: { retrait: "essai" } },
      ],
      "GET /api/workspaces/retrait/branches": { status: 200, body: BRANCHES },
      "PUT /api/workspaces/retrait/branches/view": { status: 200, body: BRANCHES[1] },
    });
    renderApp();
    const nav = await screen.findByRole("navigation");
    // Sans choix enregistré, c'est la branche de base qu'on regarde.
    expect(
      await within(nav).findByRole("button", { name: "Retrait de colis (atelier)" }),
    ).toBeInTheDocument();
    const picker = await screen.findByLabelText("Branch viewed");
    await within(picker).findByRole("option", { name: "essai" });

    fireEvent.change(picker, { target: { value: "essai" } });

    expect(
      await within(nav).findByRole("button", { name: "Retrait de colis (essai)" }),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.key === "PUT /api/workspaces/retrait/branches/view")?.body).toEqual({
      branch: "essai",
    });
  });

  it("lists the declared contracts under the branch viewed, and opens one from the menu", async () => {
    const declared = { slug: "suivi", label: "Suivi des demandes", sens: "externe", versions: [] };
    mockApi({
      ...ADMIN,
      "GET /api/workspaces": { status: 200, body: [{ ...CONFIGURED, work_branch: "back/retrait/atelier" }] },
      "GET /api/branch-views": { status: 200, body: {} },
      "GET /api/workspaces/retrait/branches": { status: 200, body: BRANCHES },
      "GET /api/workspaces/retrait/contracts?branch=atelier": { status: 200, body: [declared] },
      "GET /api/workspaces/retrait/contracts/suivi?branch=atelier": { status: 200, body: declared },
    });
    renderApp();
    const nav = await screen.findByRole("navigation");
    fireEvent.click(await within(nav).findByRole("button", { name: "Retrait de colis (atelier)" }));

    const contract = await within(nav).findByRole("button", { name: "Suivi des demandes" });
    fireEvent.click(contract);

    expect(await screen.findByRole("heading", { name: "Suivi des demandes" })).toBeInTheDocument();
    expect(contract).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("button", { name: "Contracts" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});
