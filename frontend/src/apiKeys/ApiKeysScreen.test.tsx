import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { ApiKeysScreen } from "./ApiKeysScreen";

const SECRET = "mlk_secret-de-quarante-trois-caracteres-xxxxxxxx";
const WORKSPACES = {
  status: 200,
  body: [
    { id: "retrait", name: "Retrait de colis", work_branch: "work/atelier" },
    { id: "caisse", name: "Caisse", work_branch: null },
  ],
};
const KEY = {
  id: "a".repeat(32),
  label: "Gateway yoops",
  prefix: "mlk_secret-d",
  grants: [{ workspace_id: "retrait", access: "lecture" }],
  created_at: "2026-10-22T10:00:00Z",
  created_by: "admin@local",
  revoked_at: null,
  last_used_at: null,
};

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ApiKeysScreen />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ApiKeysScreen", () => {
  it("gives the MCP address to declare in the gateway, ready to copy", async () => {
    mockApi({
      "GET /api/api-keys": { status: 200, body: [] },
      "GET /api/api-keys/endpoint": {
        status: 200,
        body: { path: "/mcp/", url: "https://svc-miles.exemple.invalid/mcp/" },
      },
    });
    renderScreen();

    expect(await screen.findByLabelText("Address to declare")).toHaveValue(
      "https://svc-miles.exemple.invalid/mcp/",
    );
    expect(screen.getByText("Copy the address")).toBeInTheDocument();
    expect(screen.getByText(/Authorization: Bearer/)).toBeInTheDocument();
  });

  it("says the public address is not configured instead of guessing one", async () => {
    mockApi({
      "GET /api/api-keys": { status: 200, body: [] },
      "GET /api/api-keys/endpoint": { status: 200, body: { path: "/mcp/", url: null } },
    });
    renderScreen();

    expect(await screen.findByText(/MILES_PUBLIC_URL is not configured/)).toHaveTextContent("/mcp/");
    expect(screen.queryByText("Copy the address")).toBeNull();
  });

  it("issues a key with its access per workspace and shows the key only once", async () => {
    const calls = mockApi({
      "GET /api/workspaces": WORKSPACES,
      "GET /api/api-keys": [
        { status: 200, body: [] },
        { status: 200, body: [KEY] },
      ],
      "POST /api/api-keys": { status: 201, body: { key: KEY, secret: SECRET } },
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Issue a key"));
    fireEvent.change(screen.getByLabelText("Label"), { target: { value: "Gateway yoops" } });
    fireEvent.change(await screen.findByLabelText(/Retrait de colis/), { target: { value: "lecture" } });
    fireEvent.click(screen.getByText("Issue the key"));

    expect(await screen.findByLabelText("API key")).toHaveTextContent(SECRET);
    expect(calls.find((c) => c.key === "POST /api/api-keys")?.body).toEqual({
      label: "Gateway yoops",
      grants: [{ workspace_id: "retrait", access: "lecture" }],
    });

    fireEvent.click(screen.getByText("I have copied it"));
    expect(await screen.findByText("mlk_secret-d…")).toBeInTheDocument();
    expect(screen.queryByText(SECRET)).toBeNull();
  });

  it("names a blank label instead of issuing", async () => {
    mockApi({
      "GET /api/workspaces": WORKSPACES,
      "GET /api/api-keys": { status: 200, body: [] },
      "POST /api/api-keys": { status: 422, body: { detail: { field: "label", reason: "vide" } } },
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Issue a key"));
    fireEvent.change(screen.getByLabelText("Label"), { target: { value: " " } });
    fireEvent.click(screen.getByText("Issue the key"));

    expect(await screen.findByText(/Label: required/)).toBeInTheDocument();
  });

  it("changes the access of a key without changing the key", async () => {
    const calls = mockApi({
      "GET /api/workspaces": WORKSPACES,
      "GET /api/api-keys": { status: 200, body: [KEY] },
      [`PUT /api/api-keys/${KEY.id}/grants`]: { status: 200, body: { ...KEY, grants: [] } },
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Change access"));
    fireEvent.change(await screen.findByLabelText(/Retrait de colis/), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText(/Caisse/), { target: { value: "ecriture" } });
    fireEvent.click(screen.getByText("Save access"));

    await screen.findByText("Gateway yoops");
    expect(calls.find((c) => c.key === `PUT /api/api-keys/${KEY.id}/grants`)?.body).toEqual({
      grants: [{ workspace_id: "caisse", access: "ecriture" }],
    });
  });

  it("revokes only after confirmation, and a revoked key offers nothing more", async () => {
    const calls = mockApi({
      "GET /api/workspaces": WORKSPACES,
      "GET /api/api-keys": [
        { status: 200, body: [KEY] },
        { status: 200, body: [{ ...KEY, revoked_at: "2026-10-22T11:00:00Z" }] },
      ],
      [`POST /api/api-keys/${KEY.id}/revoke`]: {
        status: 200,
        body: { ...KEY, revoked_at: "2026-10-22T11:00:00Z" },
      },
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Revoke"));
    expect(calls.some((c) => c.key.startsWith("POST"))).toBe(false);
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Revoke"));

    expect(await screen.findByText("revoked")).toBeInTheDocument();
    expect(screen.queryByText("Change access")).toBeNull();
    expect(screen.queryByText("Revoke")).toBeNull();
  });
});
