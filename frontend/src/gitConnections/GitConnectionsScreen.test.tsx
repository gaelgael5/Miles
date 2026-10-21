import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { GitConnectionsScreen } from "./GitConnectionsScreen";

const TOKENS = "GET /api/secrets?secret_type=GIT_TOKEN";
const TOKEN = {
  slug: "gh",
  label: "Jeton GitHub",
  secret_type: "GIT_TOKEN",
  created_at: "2026-10-21T09:00:00Z",
  updated_at: "2026-10-21T09:00:00Z",
  consumers: [],
};
const CONNECTION = {
  id: "github-acme",
  label: "GitHub Acme",
  base_url: "https://github.com/acme",
  token_secret_slug: "gh",
  workspaces: ["retrait"],
  created_at: "2026-10-21T09:00:00Z",
  updated_at: "2026-10-21T09:00:00Z",
};
const PICKERS = { [TOKENS]: { status: 200, body: [TOKEN] } };

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <GitConnectionsScreen />
    </QueryClientProvider>,
  );
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GitConnectionsScreen", () => {
  it("declares a connection by PAT, its identifier following its label", async () => {
    const calls = mockApi({
      "GET /api/git-connections": [
        { status: 200, body: [] },
        { status: 200, body: [{ ...CONNECTION, workspaces: [] }] },
      ],
      "POST /api/git-connections": { status: 201, body: CONNECTION },
      ...PICKERS,
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Add a connection"));
    fill("Label", "GitHub Acme");
    fill("Forge or organisation address", "https://github.com/acme");
    // Sans PAT, rien à envoyer : c'est le seul accès depuis le retrait du mTLS (21/10/2026).
    expect(screen.getByText("Save the connection")).toBeDisabled();
    await screen.findByRole("option", { name: "Jeton GitHub" });
    fill("PAT (access token)", "gh");

    fireEvent.click(screen.getByText("Save the connection"));

    expect(await screen.findByText("GitHub Acme")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/git-connections")?.body).toEqual({
      id: "github-acme",
      label: "GitHub Acme",
      base_url: "https://github.com/acme",
      token_secret_slug: "gh",
    });
  });

  it("shows the PAT and how many workspaces use each connection, and offers no certificate", async () => {
    mockApi({ "GET /api/git-connections": { status: 200, body: [CONNECTION] }, ...PICKERS });
    renderScreen();

    expect(await screen.findByText("gh")).toBeInTheDocument();
    expect(screen.getByText("1 workspace")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Edit"));
    expect(screen.queryByLabelText(/certificate/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/certificate/i)).not.toBeInTheDocument();
  });

  it("warns that an edit is tested on the workspaces, and names the one that would break", async () => {
    const calls = mockApi({
      "GET /api/git-connections": { status: 200, body: [CONNECTION] },
      "PUT /api/git-connections/github-acme": {
        status: 422,
        body: { detail: { code: "depot_hors_adresse", workspace: "retrait" } },
      },
      ...PICKERS,
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Edit"));
    expect(screen.getByText(/1 workspace uses this connection/)).toBeInTheDocument();
    fill("Forge or organisation address", "https://github.com/ailleurs");

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The repository of workspace retrait would no longer be under this address",
    );
    const body = calls.find((c) => c.key === "PUT /api/git-connections/github-acme")?.body as {
      verification_suffix: string;
      token_secret_slug: string;
    };
    expect(body.verification_suffix).toMatch(/^[0-9a-f]{8}$/);
    expect(body.token_secret_slug).toBe("gh");
  });

  it("refuses to delete a connection used by a workspace, after confirmation", async () => {
    mockApi({
      "GET /api/git-connections": { status: 200, body: [CONNECTION] },
      "DELETE /api/git-connections/github-acme": {
        status: 409,
        body: { detail: { code: "utilise", by: ["retrait"] } },
      },
    });
    renderScreen();

    fireEvent.click(await screen.findByText("Delete"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Delete permanently"));

    expect(await screen.findByRole("alert")).toHaveTextContent("used by the workspaces: retrait");
  });
});
