import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { ShelvesSection } from "./ShelvesSection";

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ShelvesSection />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ShelvesSection", () => {
  it("lists my shelved branches with their forge branch", async () => {
    mockApi({
      "GET /api/auth/me/shelves": {
        status: 200,
        body: [
          {
            workspace_id: "retrait",
            workspace_name: "Retrait de colis",
            slug: "edition",
            shelf_branch: "shelve/gael/edition",
            mine: true,
            shelved_at: "2026-10-23T09:00:00Z",
          },
        ],
      },
    });
    renderSection();

    expect(await screen.findByText("Shelved branches")).toBeInTheDocument();
    expect(await screen.findByRole("listitem")).toHaveTextContent(
      /Retrait de colis — branch edition, shelved on .*: shelve\/gael\/edition/,
    );
  });

  it("shows nothing when nothing is shelved", async () => {
    const calls = mockApi({ "GET /api/auth/me/shelves": { status: 200, body: [] } });
    const { container } = renderSection();

    await vi.waitFor(() => expect(calls).toHaveLength(1));
    await vi.waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
