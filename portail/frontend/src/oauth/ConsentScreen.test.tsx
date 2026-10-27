import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { ConsentScreen } from "./ConsentScreen";
import { navigation, rememberPendingAuthorize, restorePendingAuthorize } from "./pendingAuthorize";

const QUERY = "?response_type=code&client_id=mcl_1&redirect_uri=https%3A%2F%2Fclaude.ai%2Fcb&state=s";
const PARAMS = { response_type: "code", client_id: "mcl_1", redirect_uri: "https://claude.ai/cb", state: "s" };
const VIEW = {
  client: { id: "mcl_1", label: "claude.ai" },
  redirect_uri: "https://claude.ai/cb",
  allowed: [
    { workspace_id: "retrait", name: "Retrait de colis", access: "ecriture" },
    { workspace_id: "caisse", name: "Caisse", access: "ecriture" },
  ],
};

function renderConsent() {
  window.history.replaceState(null, "", `/oauth/authorize${QUERY}`);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConsentScreen />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
  sessionStorage.clear();
});

describe("ConsentScreen", () => {
  it("delegates only what was chosen, then sends the browser back to the client", async () => {
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    const calls = mockApi({
      "POST /api/oauth/authorize/check": { status: 200, body: VIEW },
      "POST /api/oauth/authorize": { status: 200, body: { redirect: "https://claude.ai/cb?code=c&state=s" } },
    });
    renderConsent();
    expect(await screen.findByText(/“claude.ai” asks to use Miles on your behalf/)).toBeInTheDocument();
    expect(screen.getByText("Authorize")).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Retrait de colis/), { target: { value: "lecture" } });
    fireEvent.click(screen.getByText("Authorize"));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://claude.ai/cb?code=c&state=s"));
    expect(calls.find((c) => c.key === "POST /api/oauth/authorize/check")?.body).toEqual(PARAMS);
    expect(calls.find((c) => c.key === "POST /api/oauth/authorize")?.body).toEqual({
      params: PARAMS,
      decision: "approve",
      grants: [{ workspace_id: "retrait", access: "lecture" }],
    });
  });

  it("lets a person without rights only refuse", async () => {
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    mockApi({
      "POST /api/oauth/authorize/check": { status: 200, body: { ...VIEW, allowed: [] } },
      "POST /api/oauth/authorize": { status: 200, body: { redirect: "https://claude.ai/cb?error=access_denied" } },
    });
    renderConsent();
    expect(await screen.findByText(/no right in Miles to delegate/)).toBeInTheDocument();
    expect(screen.queryByText("Authorize")).toBeNull();

    fireEvent.click(screen.getByText("Refuse"));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://claude.ai/cb?error=access_denied"));
  });

  it("names an unknown client on screen without redirecting anywhere", async () => {
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    mockApi({ "POST /api/oauth/authorize/check": { status: 400, body: { detail: "client_inconnu" } } });
    renderConsent();

    expect(await screen.findByText("This application is not declared in Miles.")).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

  it("hands a malformed request back to the client when its return address is safe", async () => {
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    mockApi({
      "POST /api/oauth/authorize/check": { status: 200, body: { redirect: "https://claude.ai/cb?error=invalid_request" } },
    });
    renderConsent();

    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://claude.ai/cb?error=invalid_request"));
  });
});

describe("pending authorization", () => {
  it("survives a login that comes back to the home page, once", () => {
    window.history.replaceState(null, "", `/oauth/authorize${QUERY}`);
    rememberPendingAuthorize();
    window.history.replaceState(null, "", "/");

    restorePendingAuthorize();
    expect(window.location.pathname + window.location.search).toBe(`/oauth/authorize${QUERY}`);

    window.history.replaceState(null, "", "/");
    restorePendingAuthorize();
    expect(window.location.pathname).toBe("/");
  });
});
