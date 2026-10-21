import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { GitConnectionsScreen } from "../gitConnections/GitConnectionsScreen";
import { mockApi } from "../test/mockApi";
import { CertificatesScreen } from "./CertificatesScreen";

const PUBLIC_KEY = "-----BEGIN PUBLIC KEY-----\nMFkw\n-----END PUBLIC KEY-----\n";
const PEM = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n";
const GENERATED = {
  id: "machine-de-prod",
  label: "Machine de prod",
  cert_pem: PEM,
  public_key_pem: PUBLIC_KEY,
  key_secret_slug: "machine-de-prod-cle",
  not_after: "2027-10-21T09:00:00Z",
  connections: [],
  created_at: "2026-10-21T09:00:00Z",
  updated_at: "2026-10-21T09:00:00Z",
};
const GENERATE = "POST /api/client-certificates/generate";

function renderWith(screenElement: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{screenElement}</QueryClientProvider>);
}

function fill(label: string, value: string, scope: HTMLElement = document.body) {
  fireEvent.change(within(scope).getByLabelText(label), { target: { value } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("certificate generation", () => {
  it("generates a certificate for a year by default, then shows its public key to copy", async () => {
    const calls = mockApi({
      "GET /api/client-certificates": [
        { status: 200, body: [] },
        { status: 200, body: [GENERATED] },
      ],
      [GENERATE]: { status: 201, body: GENERATED },
    });
    renderWith(<CertificatesScreen />);
    fireEvent.click(await screen.findByText("Generate a certificate"));
    expect(screen.getByLabelText("Validity (days)")).toHaveValue(365);
    fill("Label", "Machine de prod");

    fireEvent.click(screen.getByText("Generate"));

    expect(await screen.findByText("Certificate “Machine de prod” generated")).toBeInTheDocument();
    expect(screen.getByLabelText("Public key")).toHaveValue(PUBLIC_KEY);
    expect(calls.find((c) => c.key === GENERATE)?.body).toEqual({
      id: "machine-de-prod",
      label: "Machine de prod",
      validity_days: 365,
    });
  });

  it("names the validity when the server refuses it", async () => {
    mockApi({
      "GET /api/client-certificates": { status: 200, body: [] },
      [GENERATE]: { status: 422, body: { detail: { field: "validity_days" } } },
    });
    renderWith(<CertificatesScreen />);
    fireEvent.click(await screen.findByText("Generate a certificate"));
    fill("Label", "Machine");
    // Le champ borne déjà la saisie à 1–3650 : on simule le refus du serveur, qui fait foi.
    fill("Validity (days)", "30");

    fireEvent.click(screen.getByText("Generate"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Validity: 1 to 3650 days.");
  });

  it("copies the public key of a listed certificate through the clipboard when available", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("isSecureContext", true);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    mockApi({ "GET /api/client-certificates": { status: 200, body: [GENERATED] } });
    renderWith(<CertificatesScreen />);

    fireEvent.click(await screen.findByRole("button", { name: "Public key" }));
    const keyField = screen.getByLabelText("Public key").closest(".field") as HTMLElement;
    fireEvent.click(within(keyField).getByText("Copy"));

    expect(await within(keyField).findByText("Copied")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(PUBLIC_KEY);
    expect(screen.getByLabelText("Certificate (PEM)")).toHaveValue(PEM);
  });

  it("falls back to selecting the text when the page is not a secure context", async () => {
    vi.stubGlobal("isSecureContext", false);
    // jsdom n'implémente pas execCommand : on le pose pour le cas « la copie a échoué ».
    const execCommand = vi.fn(() => false);
    Object.defineProperty(document, "execCommand", { value: execCommand, configurable: true });
    mockApi({ "GET /api/client-certificates": { status: 200, body: [GENERATED] } });
    renderWith(<CertificatesScreen />);

    fireEvent.click(await screen.findByRole("button", { name: "Public key" }));
    const keyField = screen.getByLabelText("Public key").closest(".field") as HTMLElement;
    fireEvent.click(within(keyField).getByText("Copy"));

    expect(await within(keyField).findByText(/press Ctrl\+C/)).toBeInTheDocument();
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(document.activeElement).toBe(screen.getByLabelText("Public key"));
  });

  it("generates a certificate from a connection, selects it and keeps the connection input", async () => {
    const calls = mockApi({
      "GET /api/git-connections": { status: 200, body: [] },
      "GET /api/secrets?secret_type=GIT_TOKEN": { status: 200, body: [] },
      "GET /api/client-certificates": [
        { status: 200, body: [] },
        { status: 200, body: [GENERATED] },
      ],
      [GENERATE]: { status: 201, body: GENERATED },
    });
    renderWith(<GitConnectionsScreen />);
    fireEvent.click(await screen.findByText("Add a connection"));
    fill("Label", "GitHub Acme");

    fireEvent.click(screen.getByText("Generate a certificate"));
    const dialog = screen.getByRole("dialog", { name: "Generate a certificate" });
    fill("Label", "Machine de prod", dialog);
    fireEvent.click(within(dialog).getByText("Generate"));
    fireEvent.click(await within(dialog).findByText("Done"));

    await screen.findByRole("option", { name: "Machine de prod" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Client certificate")).toHaveValue("machine-de-prod");
    expect(screen.getByLabelText("Label")).toHaveValue("GitHub Acme");
    expect(calls.some((c) => c.key === "POST /api/git-connections")).toBe(false);
  });
});
