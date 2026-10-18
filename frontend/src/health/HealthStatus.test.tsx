import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import type { HealthResponse } from "../api/health";
import { HealthStatus } from "./HealthStatus";

function mockFetch(status: number, body?: HealthResponse) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body ?? {}), { status })),
  );
}

function renderStatus() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <HealthStatus />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HealthStatus", () => {
  it("shows an operational service when the schema is up to date", async () => {
    mockFetch(200, {
      status: "ok",
      database: "up",
      schema_version: 3,
      expected_schema_version: 3,
    });

    renderStatus();

    expect(await screen.findByText("Service operational")).toBeInTheDocument();
    expect(screen.getByText("Database reachable")).toBeInTheDocument();
    expect(screen.getByText("Schema version 3 of 3")).toBeInTheDocument();
  });

  it("reads the 503 body and reports a schema behind", async () => {
    mockFetch(503, {
      status: "degraded",
      database: "up",
      schema_version: 2,
      expected_schema_version: 5,
    });

    renderStatus();

    expect(await screen.findByRole("alert")).toHaveTextContent("Service degraded");
    expect(screen.getByText("Schema version 2 of 5")).toBeInTheDocument();
  });

  it("reports a database down and a never-initialised schema", async () => {
    mockFetch(503, {
      status: "degraded",
      database: "down",
      schema_version: null,
      expected_schema_version: 1,
    });

    renderStatus();

    expect(await screen.findByText("Database unreachable")).toBeInTheDocument();
    expect(
      screen.getByText("Schema never initialised (expected version 1)"),
    ).toBeInTheDocument();
  });

  it("reports the back-office unreachable on an unexpected status", async () => {
    mockFetch(502);

    renderStatus();

    expect(await screen.findByRole("alert")).toHaveTextContent("Back-office unreachable");
  });

  it("reports the back-office unreachable on a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    renderStatus();

    expect(await screen.findByRole("alert")).toHaveTextContent("Back-office unreachable");
  });
});
