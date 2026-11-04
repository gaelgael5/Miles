import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "../App";
import i18n from "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED } from "../workspaces/workspaceFixtures";

const STATUS = { "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } } };
const ADMIN_ME = {
  kind: "local_admin",
  username: "admin",
  subject: "admin",
  email: "a@b.c",
  directory: null,
  root_admin: true,
};
const OIDC_ME = {
  kind: "oidc",
  username: "Alice",
  subject: "4f1c-alice",
  email: "alice@acme.test",
  directory: "kc",
  root_admin: false,
};
const CULTURES = {
  "GET /api/auth/cultures": {
    status: 200,
    body: [
      { code: "en-US", label_native: "English" },
      { code: "fr-FR", label_native: "Français" },
      { code: "de-DE", label_native: "Deutsch" },
    ],
  },
};

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

afterEach(async () => {
  vi.unstubAllGlobals();
  await i18n.changeLanguage("en-US");
});

describe("ProfileScreen", () => {
  it("opens from the name in the top bar and shows who the session is", async () => {
    mockApi({
      ...STATUS,
      ...CULTURES,
      "GET /api/auth/me": { status: 200, body: OIDC_ME },
      "GET /api/auth/me/preferences": { status: 200, body: { language: null } },
    });
    renderApp();

    fireEvent.click(await screen.findByRole("button", { name: "alice@acme.test" }));

    expect(await screen.findByRole("heading", { name: "My profile" })).toBeInTheDocument();
    expect(screen.getByText("OIDC directory")).toBeInTheDocument();
    expect(screen.getByText("kc")).toBeInTheDocument();
    expect(screen.getByText("4f1c-alice")).toBeInTheDocument();
    // Sans droit : ni l'indicateur d'administrateur, ni les branches des workspaces.
    expect(screen.queryByText("Root administrator")).not.toBeInTheDocument();
    expect(screen.queryByText("Branch viewed per workspace")).not.toBeInTheDocument();
  });

  it("offers only translated active cultures, and applies the chosen language at once", async () => {
    const calls = mockApi({
      ...STATUS,
      ...CULTURES,
      "GET /api/auth/me": { status: 200, body: OIDC_ME },
      "GET /api/auth/me/preferences": { status: 200, body: { language: null } },
      "PUT /api/auth/me/preferences": { status: 200, body: { language: "fr-FR" } },
    });
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "alice@acme.test" }));
    const select = await screen.findByLabelText("Portal language");
    await within(select).findByRole("option", { name: "Français (fr-FR)" });

    // de-DE est active mais le portail ne la sait pas afficher : elle n'est pas proposée.
    expect(within(select).queryByRole("option", { name: /de-DE/ })).not.toBeInTheDocument();
    fireEvent.change(select, { target: { value: "fr-FR" } });

    expect(await screen.findByRole("heading", { name: "Mon profil" })).toBeInTheDocument();
    expect(calls.find((c) => c.key === "PUT /api/auth/me/preferences")?.body).toEqual({
      language: "fr-FR",
    });
  });

  it("shows the portal in the language kept for the account as soon as one signs in", async () => {
    mockApi({
      ...STATUS,
      ...CULTURES,
      "GET /api/auth/me": { status: 200, body: OIDC_ME },
      "GET /api/auth/me/preferences": { status: 200, body: { language: "fr-FR" } },
    });
    renderApp();

    expect(await screen.findByRole("button", { name: "Se déconnecter" })).toBeInTheDocument();
  });

  it("lets the administrator change the branch viewed for each workspace", async () => {
    const calls = mockApi({
      ...STATUS,
      ...CULTURES,
      "GET /api/auth/me": { status: 200, body: ADMIN_ME },
      "GET /api/auth/me/preferences": { status: 200, body: { language: null } },
      "GET /api/workspaces": { status: 200, body: [{ ...CONFIGURED, work_branch: "back/retrait/atelier" }] },
      "GET /api/branch-views": { status: 200, body: {} },
      "GET /api/workspaces/retrait/branches": {
        status: 200,
        body: [
          { slug: "atelier", label: "atelier", branch: "back/retrait/atelier", base: true },
          { slug: "essai", label: "Essai", branch: "back/retrait/essai", base: false },
        ],
      },
      "PUT /api/workspaces/retrait/branches/view": {
        status: 200,
        body: { slug: "essai", label: "Essai", branch: "back/retrait/essai", base: false },
      },
    });
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "a@b.c" }));
    const section = (await screen.findByRole("heading", { name: "Branch viewed per workspace" }))
      .parentElement as HTMLElement;
    const picker = within(section).getByLabelText("Branch viewed");
    await within(picker).findByRole("option", { name: "essai" });

    fireEvent.change(picker, { target: { value: "essai" } });

    await vi.waitFor(() =>
      expect(calls.some((c) => c.key === "PUT /api/workspaces/retrait/branches/view")).toBe(true),
    );
    expect(screen.getByText("Root administrator")).toBeInTheDocument();
  });
});
