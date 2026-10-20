import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import { mockApi } from "../test/mockApi";
import { AuthGate } from "./AuthGate";

const ME = { kind: "local_admin", username: "admin", email: "gael@example.org" };

function renderGate() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthGate>{(me) => <p>portal for {me.username}</p>}</AuthGate>
    </QueryClientProvider>,
  );
}

function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function fillBootstrap(password = "correct horse battery", confirmation = password) {
  fill("Email", "gael@example.org");
  fill("Username", "admin");
  fill("Password", password);
  fill("Confirm password", confirmation);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AuthGate", () => {
  it("shows the bootstrap screen on a blank installation", async () => {
    mockApi({ "GET /api/bootstrap/status": { status: 200, body: { admin_declared: false } } });

    renderGate();

    expect(await screen.findByText("Create the administrator account")).toBeInTheDocument();
    expect(screen.queryByText(/portal for/)).not.toBeInTheDocument();
  });

  it("shows the login screen when an admin exists but no session", async () => {
    mockApi({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } },
      "GET /api/auth/me": { status: 401, body: { detail: "session_requise" } },
    });

    renderGate();

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows the portal for a signed-in admin", async () => {
    mockApi({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } },
      "GET /api/auth/me": { status: 200, body: ME },
    });

    renderGate();

    expect(await screen.findByText("portal for admin")).toBeInTheDocument();
  });

  it("reports an unreachable back-office instead of a login screen", async () => {
    mockApi({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } },
      "GET /api/auth/me": { status: 502 },
    });

    renderGate();

    expect(await screen.findByText("Back-office unreachable")).toBeInTheDocument();
  });

  it("creates the account and lands on the portal", async () => {
    const calls = mockApi({
      "GET /api/bootstrap/status": [
        { status: 200, body: { admin_declared: false } },
        { status: 200, body: { admin_declared: true } },
      ],
      "POST /api/bootstrap": { status: 201, body: ME },
      "GET /api/auth/me": { status: 200, body: ME },
    });
    renderGate();
    await screen.findByText("Create the administrator account");

    fillBootstrap();
    fireEvent.click(screen.getByRole("button", { name: "Create the account" }));

    expect(await screen.findByText("portal for admin")).toBeInTheDocument();
    const posted = calls.find((call) => call.key === "POST /api/bootstrap");
    expect(posted?.body).toEqual({
      email: "gael@example.org",
      username: "admin",
      password: "correct horse battery",
    });
  });

  it("blocks submission when the confirmation differs", async () => {
    const calls = mockApi({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: false } },
    });
    renderGate();
    await screen.findByText("Create the administrator account");

    fillBootstrap("correct horse battery", "correct horse batterie");

    expect(screen.getByText("The two passwords differ.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create the account" })).toBeDisabled();
    expect(calls.some((call) => call.key === "POST /api/bootstrap")).toBe(false);
  });

  it("translates the password rule returned by the server", async () => {
    mockApi({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: false } },
      "POST /api/bootstrap": { status: 422, body: { detail: { rule: "min_length", limit: 12 } } },
    });
    renderGate();
    await screen.findByText("Create the administrator account");

    fillBootstrap("court");
    fireEvent.click(screen.getByRole("button", { name: "Create the account" }));

    expect(
      await screen.findByText("The password needs at least 12 characters."),
    ).toBeInTheDocument();
  });

  it("says the bootstrap is closed when another admin got there first", async () => {
    mockApi({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: false } },
      "POST /api/bootstrap": { status: 409, body: { detail: "amorcage_ferme" } },
    });
    renderGate();
    await screen.findByText("Create the administrator account");

    fillBootstrap();
    fireEvent.click(screen.getByRole("button", { name: "Create the account" }));

    expect(
      await screen.findByText("An administrator already exists: this screen is closed."),
    ).toBeInTheDocument();
  });

  it.each([
    [401, "Wrong username or password."],
    [429, "Too many failed attempts. Try again in a few minutes."],
  ])("explains a refused sign-in (HTTP %i)", async (status, message) => {
    mockApi({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } },
      "GET /api/auth/me": { status: 401 },
      "POST /api/auth/login": { status, body: { detail: "refus" } },
    });
    renderGate();
    await screen.findByRole("heading", { name: "Sign in" });

    fill("Username", "admin");
    fill("Password", "mauvais");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText(message)).toBeInTheDocument();
  });
});
