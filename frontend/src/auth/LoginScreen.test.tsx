import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { LoginScreen } from "./LoginScreen";

const CULTURES = { status: 200, body: [{ code: "en-US", label_native: "English (United States)" }] };
const LIST_EN = "GET /api/auth/oidc/connectors?culture=en-US";
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
  window.localStorage.clear();
});

describe("LoginScreen", () => {
  it("offers one sign-in link per active connector, next to the local form", async () => {
    mockApi({ "GET /api/auth/cultures": CULTURES, [LIST_EN]: { status: 200, body: CONNECTORS } });

    renderAt("");

    const link = await screen.findByRole("link", { name: "Keycloak maison" });
    expect(link).toHaveAttribute("href", "/api/auth/oidc/start?connector=kc");
    expect(screen.getByRole("link", { name: "Microsoft Entra" })).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("keeps the local sign-in alone when no connector is active", async () => {
    const calls = mockApi({ "GET /api/auth/cultures": CULTURES, [LIST_EN]: { status: 200, body: [] } });

    renderAt("");

    await vi.waitFor(() => expect(calls.map((c) => c.key)).toContain(LIST_EN));
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("explains a failed OIDC sign-in, naming the connector by its label", async () => {
    mockApi({ "GET /api/auth/cultures": CULTURES, [LIST_EN]: { status: 200, body: CONNECTORS } });

    renderAt("?login_error=fournisseur_injoignable&connector=kc");

    expect(await screen.findByText(/Keycloak maison: the identity provider cannot be reached/)).toBeInTheDocument();
  });

  it("never displays an unknown error code taken from the address", async () => {
    mockApi({ "GET /api/auth/cultures": CULTURES, [LIST_EN]: { status: 200, body: [] } });

    renderAt("?login_error=<script>alert(1)</script>");

    expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in failed. See the back-office logs.");
    expect(document.body.innerHTML).not.toContain("<script>alert");
  });
});

describe("LoginScreen cultures", () => {
  const TWO = {
    status: 200,
    body: [
      { code: "en-US", label_native: "English (United States)" },
      { code: "fr-FR", label_native: "français (France)" },
    ],
  };

  it("lets the visitor switch culture, remembers it, and asks labels in it", async () => {
    mockApi({
      "GET /api/auth/cultures": TWO,
      [LIST_EN]: { status: 200, body: [{ id: "kc", label: "Company directory" }] },
      "GET /api/auth/oidc/connectors?culture=fr-FR": {
        status: 200,
        body: [{ id: "kc", label: "Annuaire maison" }],
      },
    });
    renderAt("");
    await screen.findByRole("link", { name: "Company directory" });

    fireEvent.change(screen.getByLabelText("Language of the sign-in buttons"), {
      target: { value: "fr-FR" },
    });

    expect(await screen.findByRole("link", { name: "Annuaire maison" })).toBeInTheDocument();
    expect(window.localStorage.getItem("miles.loginCulture")).toBe("fr-FR");
  });
});
