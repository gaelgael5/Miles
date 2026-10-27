import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { GitIdentitiesSection } from "./GitIdentitiesSection";

const ROUTE = "/api/auth/me/git-identities";
const EMPTY = {
  connection_id: "acme",
  connection_label: "GitHub Acme",
  base_url: "https://github.com/acme",
  registered: false,
  account: null,
  repositories: [],
  verified_at: null,
};
const REGISTERED = {
  ...EMPTY,
  registered: true,
  account: { login: "gael", name: "Gaël", email: "7+gael@users.noreply.github.com", email_origin: "noreply" },
  repositories: [
    { workspace_id: "retrait", workspace_name: "Retrait de colis", can_write: true },
    { workspace_id: "caisse", workspace_name: "Caisse", can_write: false },
  ],
  verified_at: "2026-10-22T08:00:00Z",
};

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <GitIdentitiesSection />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GitIdentitiesSection", () => {
  it("checks and saves a personal token, then shows the account without the token", async () => {
    const calls = mockApi({
      [`GET ${ROUTE}`]: [
        { status: 200, body: [EMPTY] },
        { status: 200, body: [REGISTERED] },
      ],
      [`PUT ${ROUTE}/acme`]: { status: 200, body: REGISTERED },
    });
    renderSection();
    expect(await screen.findByText("No token registered for this connection.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Personal access token"), {
      target: { value: "ghp_personnel" },
    });
    fireEvent.click(screen.getByText("Check and save"));

    expect(await screen.findByText(/Account gael \(Gaël\)/)).toBeInTheDocument();
    // Repli de l'e-mail rendu visible, et droit d'écriture dit dépôt par dépôt.
    expect(screen.getByText(/GitHub no-reply address/)).toBeInTheDocument();
    expect(screen.getByText("Retrait de colis — can write")).toBeInTheDocument();
    expect(screen.getByText("Caisse — cannot write")).toBeInTheDocument();
    expect(screen.getByLabelText("Personal access token")).toHaveValue("");
    expect(calls.find((c) => c.key === `PUT ${ROUTE}/acme`)?.body).toEqual({ token: "ghp_personnel" });
  });

  it("says why the forge refused the token, and clears it from the page", async () => {
    mockApi({
      [`GET ${ROUTE}`]: { status: 200, body: [EMPTY] },
      [`PUT ${ROUTE}/acme`]: {
        status: 422,
        body: { detail: { code: "verification_impossible", reason: "jeton_refuse" } },
      },
    });
    renderSection();
    const field = await screen.findByLabelText("Personal access token");

    fireEvent.change(field, { target: { value: "faux" } });
    fireEvent.click(screen.getByText("Check and save"));

    expect(await screen.findByText("The forge refused this token.")).toBeInTheDocument();
    expect(field).toHaveValue("");
  });

  it("removes the token only after confirmation", async () => {
    const calls = mockApi({
      [`GET ${ROUTE}`]: [
        { status: 200, body: [REGISTERED] },
        { status: 200, body: [EMPTY] },
      ],
      [`DELETE ${ROUTE}/acme`]: { status: 204 },
    });
    renderSection();
    fireEvent.click(await screen.findByText("Remove the token"));
    expect(calls.some((c) => c.key === `DELETE ${ROUTE}/acme`)).toBe(false);

    fireEvent.click(screen.getAllByRole("button", { name: "Remove the token" }).at(-1) as HTMLElement);

    expect(await screen.findByText("No token registered for this connection.")).toBeInTheDocument();
    expect(calls.some((c) => c.key === `DELETE ${ROUTE}/acme`)).toBe(true);
  });

  it("refuses to remove the token while a branch is held, naming it", async () => {
    mockApi({
      [`GET ${ROUTE}`]: { status: 200, body: [REGISTERED] },
      [`DELETE ${ROUTE}/acme`]: {
        status: 409,
        body: { detail: { code: "prise_de_main_en_cours", workspace_id: "retrait", branch: "edition" } },
      },
    });
    renderSection();
    fireEvent.click(await screen.findByText("Remove the token"));
    fireEvent.click(screen.getAllByRole("button", { name: "Remove the token" }).at(-1) as HTMLElement);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You hold branch edition of workspace retrait: release it first",
    );
  });
});
