import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { ActorIdentitySection } from "./ActorIdentitySection";

const ROUTE = "/api/auth/me/identity";
const GUID = "7c9e6679-7425-40de-944b-e07fc1f90ae7";

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ActorIdentitySection />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ActorIdentitySection", () => {
  it("generates an identifier and saves it", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue(GUID);
    const calls = mockApi({
      [`GET ${ROUTE}`]: { status: 200, body: { actor: null } },
      [`PUT ${ROUTE}`]: { status: 200, body: { actor: GUID } },
    });
    renderSection();
    fireEvent.click(await screen.findByText("Generate"));
    expect(screen.getByLabelText("Actor identifier (GUID)")).toHaveValue(GUID);
    fireEvent.click(screen.getByText("Save"));

    expect(await screen.findByText("Remove")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `PUT ${ROUTE}`)?.body).toEqual({ actor: GUID });
  });

  it("says when the identifier is taken by someone else", async () => {
    mockApi({
      [`GET ${ROUTE}`]: { status: 200, body: { actor: null } },
      [`PUT ${ROUTE}`]: { status: 409, body: { detail: "identite_prise" } },
    });
    renderSection();
    fireEvent.change(await screen.findByLabelText("Actor identifier (GUID)"), { target: { value: GUID } });
    fireEvent.click(screen.getByText("Save"));

    expect(await screen.findByText("This identifier is already used by someone else.")).toBeInTheDocument();
  });

  it("removes the identifier", async () => {
    const calls = mockApi({
      [`GET ${ROUTE}`]: { status: 200, body: { actor: GUID } },
      [`DELETE ${ROUTE}`]: { status: 204 },
    });
    renderSection();
    expect(await screen.findByLabelText("Actor identifier (GUID)")).toHaveValue(GUID);
    fireEvent.click(screen.getByText("Remove"));

    expect(await screen.findByLabelText("Actor identifier (GUID)")).toHaveValue("");
    expect(calls.some((c) => c.key === `DELETE ${ROUTE}`)).toBe(true);
  });
});
