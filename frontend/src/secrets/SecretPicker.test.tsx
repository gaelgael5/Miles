import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { SecretPicker } from "./SecretPicker";

const OIDC = {
  slug: "oidc-kc",
  label: "Keycloak client",
  secret_type: "OIDC_CLIENT_SECRET",
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:00:00Z",
  consumers: [],
};
const LIST = "GET /api/secrets?secret_type=OIDC_CLIENT_SECRET";

/** Un écran consommateur : sa propre saisie doit survivre à une création à la volée. */
function ConnectorForm({ initial = null }: { initial?: string | null }) {
  const [name, setName] = useState("");
  const [secret, setSecret] = useState<string | null>(initial);
  const [submitted, setSubmitted] = useState(false);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setSubmitted(true);
      }}
    >
      <label>
        Connector name
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <SecretPicker label="Client secret" secretType="OIDC_CLIENT_SECRET" value={secret} onChange={setSecret} />
      <output aria-label="stored">{secret ?? "none"}</output>
      {submitted && <p>connector form submitted</p>}
    </form>
  );
}

function renderForm(initial?: string | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConnectorForm initial={initial} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SecretPicker", () => {
  it("offers only secrets of the field's type, by label, and stores the slug", async () => {
    const calls = mockApi({ [LIST]: { status: 200, body: [OIDC] } });
    renderForm();

    const select = await screen.findByLabelText("Client secret");
    await screen.findByRole("option", { name: "Keycloak client" });
    fireEvent.change(select, { target: { value: "oidc-kc" } });

    expect(screen.getByLabelText("stored")).toHaveTextContent("oidc-kc");
    expect(calls.map((c) => c.key)).toContain(LIST);
    expect(screen.queryByRole("textbox", { name: "Client secret" })).not.toBeInTheDocument();
  });

  it("creates a secret inline without losing the calling form's input", async () => {
    const calls = mockApi({
      [LIST]: [
        { status: 200, body: [] },
        { status: 200, body: [OIDC] },
      ],
      "POST /api/secrets": { status: 201, body: OIDC },
    });
    renderForm();
    fireEvent.change(screen.getByLabelText("Connector name"), { target: { value: "Keycloak" } });

    fireEvent.click(await screen.findByText("Create a secret"));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Type: OIDC_CLIENT_SECRET");
    fireEvent.change(screen.getByLabelText("Label"), { target: { value: "Keycloak client" } });
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "s3cr3t" } });
    fireEvent.click(screen.getByText("Save the secret"));

    expect(await screen.findByLabelText("stored")).toHaveTextContent("oidc-kc");
    await screen.findByRole("option", { name: "Keycloak client" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Connector name")).toHaveValue("Keycloak");
    expect(screen.queryByText("connector form submitted")).not.toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/secrets")?.body).toMatchObject({
      slug: "keycloak-client",
      secret_type: "OIDC_CLIENT_SECRET",
    });
  });

  it("flags a reference to a secret that no longer exists instead of clearing it", async () => {
    mockApi({ [LIST]: { status: 200, body: [OIDC] } });

    renderForm("deleted-secret");

    expect(await screen.findByRole("alert")).toHaveTextContent("deleted-secret");
    expect(screen.getByLabelText("stored")).toHaveTextContent("deleted-secret");
    expect(screen.getByLabelText("Client secret")).toHaveValue("deleted-secret");
  });
});
