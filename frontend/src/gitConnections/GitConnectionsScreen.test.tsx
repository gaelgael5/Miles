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
const CERTIFICATE = {
  id: "machine",
  label: "Machine de prod",
  cert_pem: "PEM",
  key_secret_slug: "cle",
  not_after: "2027-10-21T09:00:00Z",
  connections: [],
  created_at: "2026-10-21T09:00:00Z",
  updated_at: "2026-10-21T09:00:00Z",
};
const CONNECTION = {
  id: "github-acme",
  label: "GitHub Acme",
  base_url: "https://github.com/acme",
  token_secret_slug: "gh",
  certificate_id: "machine",
  workspaces: ["retrait"],
  created_at: "2026-10-21T09:00:00Z",
  updated_at: "2026-10-21T09:00:00Z",
};
const PICKERS = {
  [TOKENS]: { status: 200, body: [TOKEN] },
  "GET /api/client-certificates": { status: 200, body: [CERTIFICATE] },
};

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
        { status: 200, body: [{ ...CONNECTION, certificate_id: null, workspaces: [] }] },
      ],
      "POST /api/git-connections": { status: 201, body: CONNECTION },
      ...PICKERS,
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Add a connection"));
    fill("Label", "GitHub Acme");
    fill("Forge or organisation address", "https://github.com/acme");
    // Ni PAT ni certificat : rien à envoyer (au moins l'un des deux, 21/10/2026).
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
      certificate_id: null,
    });
  });

  it("shows the means of access and how many workspaces use each connection", async () => {
    mockApi({ "GET /api/git-connections": { status: 200, body: [CONNECTION] } });
    renderScreen();

    expect(await screen.findByText("PAT")).toBeInTheDocument();
    expect(screen.getByText("Certificate")).toBeInTheDocument();
    expect(screen.getByText("1 workspace")).toBeInTheDocument();
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
      certificate_id: string;
    };
    expect(body.verification_suffix).toMatch(/^[0-9a-f]{8}$/);
    expect(body.certificate_id).toBe("machine");
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
