import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { LoginScreen } from "./LoginScreen";

const CONNECTORS = [
  { id: "kc", label: "Keycloak maison" },
  { id: "entra", label: "Microsoft Entra" },
];

function renderAt(search: string) {
  window.history.replaceState(null, "", `/${search}`);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LoginScreen />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

describe("LoginScreen", () => {
  it("offers one sign-in link per active connector, next to the local form", async () => {
    mockApi({ "GET /api/auth/oidc/connectors": { status: 200, body: CONNECTORS } });

    renderAt("");

    const link = await screen.findByRole("link", { name: "Keycloak maison" });
    expect(link).toHaveAttribute("href", "/api/auth/oidc/start?connector=kc");
    expect(screen.getByRole("link", { name: "Microsoft Entra" })).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("keeps the local sign-in alone when no connector is active", async () => {
    const calls = mockApi({ "GET /api/auth/oidc/connectors": { status: 200, body: [] } });

    renderAt("");

    await vi.waitFor(() => expect(calls.length).toBe(1));
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("explains a failed OIDC sign-in, naming the connector by its label", async () => {
    mockApi({ "GET /api/auth/oidc/connectors": { status: 200, body: CONNECTORS } });

    renderAt("?login_error=fournisseur_injoignable&connector=kc");

    expect(await screen.findByText(/Keycloak maison: the identity provider cannot be reached/)).toBeInTheDocument();
  });

  it("never displays an unknown error code taken from the address", async () => {
    mockApi({ "GET /api/auth/oidc/connectors": { status: 200, body: [] } });

    renderAt("?login_error=<script>alert(1)</script>");

    expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in failed. See the back-office logs.");
    expect(document.body.innerHTML).not.toContain("<script>alert");
  });
});
