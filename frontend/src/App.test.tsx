import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import { App } from "./App";
import "./i18n/i18n";
import { mockApi } from "./test/mockApi";

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("gives an OIDC session without roles nothing but its identity and sign-out", async () => {
    mockApi({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } },
      "GET /api/auth/me": {
        status: 200,
        body: { kind: "oidc", username: "Alice", email: null, directory: "kc" },
      },
    });

    renderApp();

    expect(await screen.findByText(/signed in through kc, but no right/)).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("gives the bootstrap administrator the portal navigation", async () => {
    mockApi({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } },
      "GET /api/auth/me": {
        status: 200,
        body: { kind: "local_admin", username: "admin", email: "a@b.c", directory: null },
      },
      "GET /api/health": { status: 200, body: {} },
    });

    renderApp();

    expect(await screen.findByRole("button", { name: "OIDC" })).toBeInTheDocument();
  });
});
