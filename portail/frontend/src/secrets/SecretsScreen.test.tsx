import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { slugFromLabel } from "../api/secrets";
import { mockApi } from "../test/mockApi";
import { SecretsScreen } from "./SecretsScreen";

const VALUE = "ghp_valeur-a-ne-jamais-garder";
const TYPES = { status: 200, body: { types: ["OIDC_CLIENT_SECRET", "GIT_TOKEN"] } };
const GIT = {
  slug: "git-token",
  label: "Jeton GitHub",
  secret_type: "GIT_TOKEN",
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:00:00Z",
  consumers: [],
};

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SecretsScreen />
    </QueryClientProvider>,
  );
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("slugFromLabel", () => {
  it("lowercases, strips accents and joins words with dashes", () => {
    expect(slugFromLabel("  Clé d'accès GitHub — prod ")).toBe("cle-d-acces-github-prod");
    expect(slugFromLabel("x".repeat(80))).toHaveLength(63);
  });
});

describe("SecretsScreen", () => {
  it("offers the secret type as a list of the types the API admits, never free text", async () => {
    mockApi({ "GET /api/secrets": { status: 200, body: [] }, "GET /api/secret-types": TYPES });
    renderScreen();
    fireEvent.click(await screen.findByText("Add a secret"));

    const type = screen.getByLabelText("Type");
    await screen.findByRole("option", { name: "OIDC connector client secret" });

    expect(type.tagName).toBe("SELECT");
    expect(screen.getAllByRole("option").map((o) => o.getAttribute("value"))).toEqual([
      "",
      "OIDC_CLIENT_SECRET",
      "GIT_TOKEN",
    ]);
  });

  it("says so when no secret exists", async () => {
    mockApi({ "GET /api/secrets": { status: 200, body: [] } });

    renderScreen();

    expect(await screen.findByText("No secret declared yet.")).toBeInTheDocument();
  });

  it("creates a secret with a slug proposed from the label, then forgets the value", async () => {
    const calls = mockApi({
      "GET /api/secrets": [
        { status: 200, body: [] },
        { status: 200, body: [GIT] },
      ],
      "POST /api/secrets": { status: 201, body: GIT },
      "GET /api/secret-types": TYPES,
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Add a secret"));

    fill("Label", "Jeton GitHub");
    await screen.findByRole("option", { name: "Git service account token" });
    fill("Type", "GIT_TOKEN");
    fill("Value", VALUE);
    fireEvent.click(screen.getByText("Save the secret"));

    expect(await screen.findByText("Jeton GitHub")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/secrets")?.body).toEqual({
      slug: "jeton-github",
      label: "Jeton GitHub",
      secret_type: "GIT_TOKEN",
      value: VALUE,
    });
    expect(document.body.innerHTML).not.toContain(VALUE);
  });

  it("names the refused field and a taken slug", async () => {
    mockApi({
      "GET /api/secrets": { status: 200, body: [] },
      "POST /api/secrets": [
        { status: 422, body: { detail: { field: "value" } } },
        { status: 409, body: { detail: "slug_pris" } },
      ],
      "GET /api/secret-types": TYPES,
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Add a secret"));
    fill("Label", "Jeton");
    await screen.findByRole("option", { name: "Git service account token" });
    fill("Type", "GIT_TOKEN");
    fill("Value", "${local://x}");

    fireEvent.click(screen.getByText("Save the secret"));
    expect(await screen.findByRole("alert")).toHaveTextContent("never a ${…} reference");

    fireEvent.click(screen.getByText("Save the secret"));
    expect(await screen.findByText(/already used by another secret/)).toBeInTheDocument();
  });

  it("lists the consumers when deleting a secret still in use", async () => {
    mockApi({
      "GET /api/secrets": { status: 200, body: [{ ...GIT, consumers: [{ kind: "workspace", id: "ws-1" }] }] },
      "DELETE /api/secrets/git-token": {
        status: 409,
        body: { detail: { code: "secret_utilise", consumers: [{ kind: "workspace", id: "ws-1" }] } },
      },
    });
    renderScreen();

    fireEvent.click(await screen.findByText("Delete"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Delete permanently"));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("still used");
    expect(within(alert).getByText("workspace ws-1")).toBeInTheDocument();
  });

  it("asks for confirmation before deleting, and deletes nothing on cancel", async () => {
    const calls = mockApi({
      "GET /api/secrets": { status: 200, body: [GIT] },
      "DELETE /api/secrets/git-token": { status: 204 },
    });
    renderScreen();

    fireEvent.click(await screen.findByText("Delete"));
    const dialog = screen.getByRole("dialog", { name: "Delete this secret?" });
    expect(dialog).toHaveTextContent("Jeton GitHub");
    expect(dialog).toHaveTextContent("git-token");
    expect(within(dialog).getByText("Cancel")).toHaveFocus();
    fireEvent.click(within(dialog).getByText("Cancel"));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Delete"));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(calls.some((c) => c.key === "DELETE /api/secrets/git-token")).toBe(false);
  });

  it("deletes the secret once the deletion is confirmed", async () => {
    const calls = mockApi({
      "GET /api/secrets": { status: 200, body: [GIT] },
      "DELETE /api/secrets/git-token": { status: 204 },
    });
    renderScreen();

    fireEvent.click(await screen.findByText("Delete"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Delete permanently"));

    await vi.waitFor(() =>
      expect(calls.some((c) => c.key === "DELETE /api/secrets/git-token")).toBe(true),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("warns in the confirmation that a secret in use will be refused", async () => {
    mockApi({
      "GET /api/secrets": { status: 200, body: [{ ...GIT, consumers: [{ kind: "workspace", id: "ws-1" }] }] },
    });
    renderScreen();

    fireEvent.click(await screen.findByText("Delete"));

    expect(screen.getByRole("dialog")).toHaveTextContent("used by 1 object");
  });

  it("replaces a value without ever displaying the old one", async () => {
    const calls = mockApi({
      "GET /api/secrets": { status: 200, body: [GIT] },
      "PUT /api/secrets/git-token/value": { status: 204 },
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Replace the value"));

    expect(screen.getByLabelText("New value")).toHaveValue("");
    expect(screen.getByLabelText("New value")).toHaveAttribute("type", "password");
    fill("New value", VALUE);
    fireEvent.click(screen.getByText("Save"));

    await screen.findByText("Replace the value");
    expect(calls.find((c) => c.key === "PUT /api/secrets/git-token/value")?.body).toEqual({
      value: VALUE,
    });
  });
});
