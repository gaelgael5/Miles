import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { SecurityServiceScreen } from "./SecurityServiceScreen";

const SECRETS = "GET /api/secrets?secret_type=SECURITY_SERVICE_CLIENT_SECRET";
const SECRET = {
  slug: "kc",
  label: "Secret Keycloak",
  secret_type: "SECURITY_SERVICE_CLIENT_SECRET",
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:00:00Z",
  consumers: [],
};
const SERVICE = {
  id: "racine",
  kind: "keycloak",
  base_url: "https://security.example.org",
  realm: "miles",
  client_id: "miles-bo",
  client_secret_slug: "kc",
  last_check_outcome: "ok",
  last_check_at: "2026-10-20T10:00:00Z",
  dependent_installations: 0,
};

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SecurityServiceScreen />
    </QueryClientProvider>,
  );
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SecurityServiceScreen", () => {
  it("declares the service with its secret picked among declared secrets", async () => {
    const calls = mockApi({
      "GET /api/security-services": [
        { status: 200, body: [] },
        { status: 200, body: [SERVICE] },
      ],
      [SECRETS]: { status: 200, body: [SECRET] },
      "POST /api/security-services": { status: 201, body: SERVICE },
    });
    renderScreen();

    await screen.findByLabelText("Address");
    fill("Address", SERVICE.base_url);
    fill("Realm", "miles");
    fill("Client ID", "miles-bo");
    await screen.findByRole("option", { name: "Secret Keycloak" });
    fill("Client secret", "kc");
    fireEvent.click(screen.getByText("Save and verify"));

    expect(await screen.findByText(/reachable, realm recognised/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/security-services")?.body).toEqual({
      id: "racine",
      base_url: SERVICE.base_url,
      realm: "miles",
      client_id: "miles-bo",
      client_secret_slug: "kc",
    });
  });

  it("names the service when it is unreachable", async () => {
    mockApi({
      "GET /api/security-services": {
        status: 200,
        body: [{ ...SERVICE, last_check_outcome: "injoignable" }],
      },
    });

    renderScreen();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Security service racine is unreachable. Terminals cannot start.",
    );
  });

  it("asks for confirmation before changing a service installations depend on", async () => {
    mockApi({
      "GET /api/security-services": {
        status: 200,
        body: [{ ...SERVICE, dependent_installations: 12 }],
      },
      [SECRETS]: { status: 200, body: [SECRET] },
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Edit"));

    const save = screen.getByText("Save and verify");
    expect(save).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/12 enrolled installations depend/));

    expect(save).toBeEnabled();
  });
});
