import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { JSX } from "react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { OAuthGrantsSection } from "../profile/OAuthGrantsSection";
import { OAuthClientsScreen } from "./OAuthClientsScreen";

const ENDPOINTS = {
  mcp_url: "https://miles.exemple.invalid/mcp/",
  issuer: "https://miles.exemple.invalid",
  authorization_endpoint: "https://miles.exemple.invalid/oauth/authorize",
  token_endpoint: "https://miles.exemple.invalid/oauth/token",
  suggested_redirect_uris: ["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"],
};
const CLIENT = {
  id: "mcl_" + "a".repeat(32),
  label: "claude.ai",
  redirect_uris: ENDPOINTS.suggested_redirect_uris,
  created_at: "2026-10-22T10:00:00Z",
};

function renderWith(node: JSX.Element) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("OAuthClientsScreen", () => {
  it("declares claude.ai with its proposed return addresses and shows its client ID", async () => {
    const calls = mockApi({
      "GET /api/oauth-clients/endpoints": { status: 200, body: ENDPOINTS },
      "GET /api/oauth-clients": [
        { status: 200, body: [] },
        { status: 200, body: [CLIENT] },
      ],
      "POST /api/oauth-clients": { status: 201, body: CLIENT },
    });
    renderWith(<OAuthClientsScreen />);
    expect(await screen.findByLabelText("MCP server URL")).toHaveValue(ENDPOINTS.mcp_url);

    fireEvent.click(screen.getByText("Declare a client"));
    expect(screen.getByLabelText("Return addresses")).toHaveValue(ENDPOINTS.suggested_redirect_uris.join("\n"));
    fireEvent.click(screen.getByText("Declare the client"));

    expect(await screen.findByText(CLIENT.id)).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/oauth-clients")?.body).toEqual({
      label: "claude.ai",
      redirect_uris: ENDPOINTS.suggested_redirect_uris,
    });
  });

  it("says OAuth stays closed without a public address", async () => {
    mockApi({
      "GET /api/oauth-clients/endpoints": {
        status: 200,
        body: { mcp_url: null, issuer: null, authorization_endpoint: null, token_endpoint: null, suggested_redirect_uris: [] },
      },
      "GET /api/oauth-clients": { status: 200, body: [] },
    });
    renderWith(<OAuthClientsScreen />);

    expect(await screen.findByText(/OAuth stays closed/)).toBeInTheDocument();
  });

  it("deletes a client only after confirmation", async () => {
    const calls = mockApi({
      "GET /api/oauth-clients/endpoints": { status: 200, body: ENDPOINTS },
      "GET /api/oauth-clients": [
        { status: 200, body: [CLIENT] },
        { status: 200, body: [] },
      ],
      [`DELETE /api/oauth-clients/${CLIENT.id}`]: { status: 204 },
    });
    renderWith(<OAuthClientsScreen />);
    fireEvent.click(await screen.findByText("Delete"));
    expect(calls.some((c) => c.key.startsWith("DELETE"))).toBe(false);
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Delete"));

    expect(await screen.findByText("No OAuth client declared.")).toBeInTheDocument();
  });
});

describe("OAuthGrantsSection", () => {
  it("lists what was authorized and revokes it", async () => {
    const calls = mockApi({
      "GET /api/auth/me/oauth-grants": [
        {
          status: 200,
          body: [{ id: "g1", client: "claude.ai", grants: { retrait: "lecture" }, created_at: "2026-10-22T10:00:00Z", last_used_at: null }],
        },
        { status: 200, body: [] },
      ],
      "DELETE /api/auth/me/oauth-grants/g1": { status: 204 },
    });
    renderWith(<OAuthGrantsSection />);
    expect(await screen.findByText("retrait (read)")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Revoke"));

    expect(await screen.findByText("You have not authorized any application.")).toBeInTheDocument();
    expect(calls.some((c) => c.key === "DELETE /api/auth/me/oauth-grants/g1")).toBe(true);
  });
});
