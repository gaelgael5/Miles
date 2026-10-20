import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { ConnectorsScreen } from "./ConnectorsScreen";

const SECRETS = "GET /api/secrets?secret_type=OIDC_CLIENT_SECRET";
const SECRET = {
  slug: "kc-secret",
  label: "Secret Keycloak",
  secret_type: "OIDC_CLIENT_SECRET",
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:00:00Z",
  consumers: [],
};
const KC = {
  id: "kc",
  label: "Keycloak",
  issuer: "https://security.example.org/realms/miles",
  client_id: "miles",
  client_secret_slug: "kc-secret",
  scopes: "openid email profile",
  active: true,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:00:00Z",
};

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConnectorsScreen />
    </QueryClientProvider>,
  );
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ConnectorsScreen", () => {
  it("declares a connector whose client secret is picked, never typed", async () => {
    const calls = mockApi({
      "GET /api/oidc/connectors": [
        { status: 200, body: [] },
        { status: 200, body: [KC] },
      ],
      [SECRETS]: { status: 200, body: [SECRET] },
      "POST /api/oidc/connectors": { status: 201, body: KC },
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Add a connector"));

    fill("Identifier", "kc");
    fill("Label", "Keycloak");
    fill("Issuer (provider address)", KC.issuer);
    fill("Client ID", "miles");
    await screen.findByRole("option", { name: "Secret Keycloak" });
    expect(screen.getByLabelText("Client secret").tagName).toBe("SELECT");
    fill("Client secret", "kc-secret");
    fireEvent.click(screen.getByText("Save"));

    expect(await screen.findByText("Keycloak")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/oidc/connectors")?.body).toEqual({
      id: "kc",
      label: "Keycloak",
      issuer: KC.issuer,
      client_id: "miles",
      client_secret_slug: "kc-secret",
      scopes: "openid email profile",
      active: true,
    });
  });

  it("edits a connector sending only the editable fields", async () => {
    const calls = mockApi({
      "GET /api/oidc/connectors": { status: 200, body: [KC] },
      [SECRETS]: { status: 200, body: [SECRET] },
      "PUT /api/oidc/connectors/kc": { status: 200, body: { ...KC, active: false } },
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Edit"));

    fireEvent.click(screen.getByLabelText("Active (offered on the sign-in screen)"));
    fireEvent.click(screen.getByText("Save"));

    await screen.findByText("Add a connector");
    const body = calls.find((c) => c.key === "PUT /api/oidc/connectors/kc")?.body;
    expect(body).toEqual({
      label: "Keycloak",
      issuer: KC.issuer,
      client_id: "miles",
      client_secret_slug: "kc-secret",
      scopes: "openid email profile",
      active: false,
    });
  });

  it("says when the provider does not answer at declaration", async () => {
    mockApi({
      "GET /api/oidc/connectors": { status: 200, body: [KC] },
      [SECRETS]: { status: 200, body: [SECRET] },
      "PUT /api/oidc/connectors/kc": {
        status: 422,
        body: { detail: { field: "issuer", reason: "injoignable" } },
      },
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Edit"));

    fireEvent.click(screen.getByText("Save"));

    expect(await screen.findByRole("alert")).toHaveTextContent("does not answer at this address");
  });

  it("suggests deactivating a connector accounts already signed in through", async () => {
    mockApi({
      "GET /api/oidc/connectors": { status: 200, body: [KC] },
      "DELETE /api/oidc/connectors/kc": {
        status: 409,
        body: { detail: { code: "connecteur_utilise", identities: 3 } },
      },
    });
    renderScreen();

    fireEvent.click(await screen.findByText("Delete"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Deactivate it instead.");
  });
});
