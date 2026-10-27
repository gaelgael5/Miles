import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import "../i18n/i18n";
import { type Culture, matchesFilter } from "../api/cultures";
import { mockApi } from "../test/mockApi";
import { CulturesScreen } from "./CulturesScreen";

const EN: Culture = {
  code: "en-US",
  label_en: "English (United States)",
  label_native: "English (United States)",
  active: true,
};
const FR: Culture = { code: "fr-FR", label_en: "French (France)", label_native: "français (France)", active: false };
const DE: Culture = { code: "de-DE", label_en: "German (Germany)", label_native: "Deutsch (Deutschland)", active: false };
const ALL = [DE, EN, FR];

function renderScreen() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CulturesScreen />
    </QueryClientProvider>,
  );
}

function filterBy(text: string) {
  fireEvent.change(screen.getByLabelText("Filter by code or name"), { target: { value: text } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("matchesFilter", () => {
  it("matches code and both labels, ignoring case and accents", () => {
    expect(matchesFilter(FR, "FR-fr")).toBe(true);
    expect(matchesFilter(FR, "FRANCAIS")).toBe(true);
    expect(matchesFilter(FR, "french")).toBe(true);
    expect(matchesFilter(FR, "deutsch")).toBe(false);
    expect(matchesFilter(FR, "  ")).toBe(true);
  });
});

describe("CulturesScreen", () => {
  it("marks active cultures and locks the en-US fallback", async () => {
    mockApi({ "GET /api/cultures": { status: 200, body: ALL } });

    renderScreen();

    const fallback = await screen.findByRole("checkbox", { name: /en-US/ });
    expect(fallback).toBeDisabled();
    expect(screen.getByText("(fallback of the installation, always active)")).toBeInTheDocument();
    expect(screen.getAllByText("Active")).toHaveLength(1);
  });

  it("says so when the filter matches nothing", async () => {
    mockApi({ "GET /api/cultures": { status: 200, body: ALL } });
    renderScreen();
    await screen.findByText(/français/);

    filterBy("klingon");

    expect(screen.getByRole("status")).toHaveTextContent("No culture matches “klingon”.");
  });

  it("acts on the selection, not on what the filter currently shows", async () => {
    const calls = mockApi({
      "GET /api/cultures": [
        { status: 200, body: ALL },
        { status: 200, body: [DE, EN, { ...FR, active: true }] },
      ],
      "POST /api/cultures/activation": { status: 200, body: { changed: ["fr-FR"] } },
    });
    renderScreen();
    fireEvent.click(await screen.findByRole("checkbox", { name: /fr-FR/ }));

    filterBy("deutsch");
    expect(screen.queryByText(/français/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Activate the selection"));

    await screen.findByText("0 cultures selected");
    expect(calls.find((c) => c.key === "POST /api/cultures/activation")?.body).toEqual({
      codes: ["fr-FR"],
      active: true,
    });
  });

  it("explains a refused deactivation of the fallback", async () => {
    mockApi({
      "GET /api/cultures": { status: 200, body: ALL },
      "POST /api/cultures/activation": { status: 422, body: { detail: { code: "repli_obligatoire" } } },
    });
    renderScreen();
    fireEvent.click(await screen.findByRole("checkbox", { name: /fr-FR/ }));

    fireEvent.click(screen.getByText("Deactivate the selection"));

    expect(await screen.findByRole("alert")).toHaveTextContent("cannot be deactivated");
  });
});
