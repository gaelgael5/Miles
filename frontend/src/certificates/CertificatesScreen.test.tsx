import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { CertificatesScreen } from "./CertificatesScreen";

const KEYS = "GET /api/secrets?secret_type=GIT_CLIENT_KEY";
const KEY = {
  slug: "cle-machine",
  label: "Clé machine",
  secret_type: "GIT_CLIENT_KEY",
  created_at: "2026-10-21T09:00:00Z",
  updated_at: "2026-10-21T09:00:00Z",
  consumers: [],
};
const PEM = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n";

function certificate(days: number, connections: string[] = []) {
  return {
    id: "machine",
    label: "Machine de prod",
    cert_pem: PEM,
    key_secret_slug: "cle-machine",
    not_after: new Date(Date.now() + days * 86_400_000).toISOString(),
    connections,
    created_at: "2026-10-21T09:00:00Z",
    updated_at: "2026-10-21T09:00:00Z",
  };
}

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CertificatesScreen />
    </QueryClientProvider>,
  );
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CertificatesScreen", () => {
  it("declares a certificate whose identifier follows its label", async () => {
    const calls = mockApi({
      "GET /api/client-certificates": [
        { status: 200, body: [] },
        { status: 200, body: [certificate(200)] },
      ],
      [KEYS]: { status: 200, body: [KEY] },
      "POST /api/client-certificates": { status: 201, body: certificate(200) },
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Import a certificate"));
    // Le bouton dit ce qu'il crée : la clé privée, pas « un secret ».
    expect(screen.getByText("Add the private key")).toBeInTheDocument();
    fill("Label", "Machine de prod");
    fill("Certificate (PEM)", PEM);
    await screen.findByRole("option", { name: "Clé machine" });
    fill("Certificate private key", "cle-machine");

    fireEvent.click(screen.getByText("Save the certificate"));

    expect(await screen.findByText("Machine de prod")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/client-certificates")?.body).toEqual({
      id: "machine-de-prod",
      label: "Machine de prod",
      cert_pem: PEM,
      key_secret_slug: "cle-machine",
    });
  });

  it("names the field when the key does not match the certificate", async () => {
    mockApi({
      "GET /api/client-certificates": { status: 200, body: [] },
      [KEYS]: { status: 200, body: [KEY] },
      "POST /api/client-certificates": {
        status: 422,
        body: { detail: { field: "key_secret_slug", reason: "ne_correspond_pas" } },
      },
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Import a certificate"));
    fill("Label", "Machine");
    fill("Certificate (PEM)", PEM);
    await screen.findByRole("option", { name: "Clé machine" });
    fill("Certificate private key", "cle-machine");

    fireEvent.click(screen.getByText("Save the certificate"));

    expect(await screen.findByRole("alert")).toHaveTextContent("does not match this certificate");
  });

  it("warns when a certificate is close to its expiry, and says when it has expired", async () => {
    mockApi({
      "GET /api/client-certificates": {
        status: 200,
        body: [certificate(5), { ...certificate(-1), id: "vieux", label: "Vieux" }],
      },
    });
    renderScreen();

    expect(await screen.findByText(/\(5 days left\)|\(4 days left\)/)).toHaveClass("badge-warning");
    expect(screen.getByText(/Expired on/)).toBeInTheDocument();
  });

  it("refuses to delete a certificate used by a connection, after confirmation", async () => {
    const calls = mockApi({
      "GET /api/client-certificates": { status: 200, body: [certificate(200, ["acme"])] },
      "DELETE /api/client-certificates/machine": {
        status: 409,
        body: { detail: { code: "utilise", by: ["acme"] } },
      },
    });
    renderScreen();

    fireEvent.click(await screen.findByText("Delete"));
    expect(calls.some((c) => c.key === "DELETE /api/client-certificates/machine")).toBe(false);
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Delete permanently"));

    expect(await screen.findByRole("alert")).toHaveTextContent("used by the connections: acme");
  });

  it("keeps the old certificate when a workspace would lose access, naming it", async () => {
    const report = {
      branch: "miles-verification-0a1b2c3d",
      tag: "miles-verification-0a1b2c3d",
      checks: [{ right: "lire", ok: false, reason: "certificat" }],
      residual_branch: null,
      residual_tag: null,
      existing_branches: 1,
      initialized_branch: null,
      all_passed: false,
    };
    const calls = mockApi({
      "GET /api/client-certificates": { status: 200, body: [certificate(200, ["acme"])] },
      [KEYS]: { status: 200, body: [KEY] },
      "PUT /api/client-certificates/machine": {
        status: 422,
        body: {
          detail: { code: "acces_insuffisant", workspace: "retrait", right: "lire", reason: "certificat", report },
        },
      },
    });
    renderScreen();
    fireEvent.click(await screen.findByText("Replace"));
    fill("Certificate (PEM)", PEM);
    await screen.findByRole("option", { name: "Clé machine" });
    fill("Certificate private key", "cle-machine");

    fireEvent.click(screen.getByText("Test and replace"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Workspace retrait would lose access to its repository",
    );
    const body = calls.find((c) => c.key === "PUT /api/client-certificates/machine")?.body as {
      verification_suffix: string;
    };
    expect(body.verification_suffix).toMatch(/^[0-9a-f]{8}$/);
  });
});
