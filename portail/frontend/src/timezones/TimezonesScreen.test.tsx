import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { Timezone } from "../api/timezones";
import { TimezonesScreen } from "./TimezonesScreen";
import "../i18n/i18n";

// L'écran des fuseaux : jumeau de celui des pays. Ce qui est éprouvé ici est ce qui lui est
// PROPRE — l'identifiant IANA toujours visible, les pays de chaque fuseau, et le filtre par
// pays. Ce qui est commun aux deux écrans l'est déjà chez les pays.

const PARIS: Timezone = {
  slug: "Europe/Paris",
  label: "Central European Time",
  // Deux pays, et c'est la vérité d'IANA : `FR,MC`.
  countries: ["FRA", "MCO"],
  active: false,
};
const BRUXELLES: Timezone = {
  slug: "Europe/Brussels",
  label: "Central European Time",
  countries: ["BEL", "LUX", "NLD"],
  active: true,
};

function monte(routes: Routes) {
  const appels = mockApi(routes);
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <TimezonesScreen />
    </QueryClientProvider>,
  );
  return appels;
}

describe("écran des fuseaux horaires", () => {
  it("shows the IANA identifier next to the label, which two zones share", async () => {
    // Le cas qui justifie la règle : les deux fuseaux ont le MÊME libellé. Sans
    // l'identifiant, l'écran afficherait deux lignes indiscernables.
    monte({ "GET /api/timezones": { status: 200, body: [BRUXELLES, PARIS] } });

    expect(await screen.findByText("Europe/Paris")).toBeInTheDocument();
    expect(screen.getByText("Europe/Brussels")).toBeInTheDocument();
    expect(screen.getAllByText("Central European Time")).toHaveLength(2);
  });

  it("shows every country of a zone, not just the first", async () => {
    // 93 pays n'apparaissent jamais en première position : n'en montrer qu'un les
    // rendrait invisibles.
    monte({ "GET /api/timezones": { status: 200, body: [BRUXELLES] } });

    expect(await screen.findByText("BEL, LUX, NLD")).toBeInTheDocument();
  });

  it("sends the country filter to the server, in upper case", async () => {
    // L'alpha-3 est saisi comme on le lit sur l'écran des pays. La mise en majuscules est
    // faite ici pour que « lux » trouve quelque chose — le slug, lui, est en majuscules.
    const appels = monte({ "GET /api/timezones": { status: 200, body: [BRUXELLES] } });

    await screen.findByText("Europe/Brussels");
    fireEvent.change(screen.getByLabelText(/Show only the zones of one country/i), {
      target: { value: "lux" },
    });

    await waitFor(() => {
      expect(appels.some((a) => a.key.includes("country=LUX"))).toBe(true);
    });
  });

  it("says the offset is not stored, because it would be wrong half the year", async () => {
    monte({ "GET /api/timezones": { status: 200, body: [PARIS] } });

    expect(await screen.findByText(/UTC offset is not stored/i)).toBeInTheDocument();
    expect(screen.getByText(/daylight saving rules/i)).toBeInTheDocument();
  });

  it("activates exactly what is checked", async () => {
    const appels = monte({
      "GET /api/timezones": { status: 200, body: [PARIS, BRUXELLES] },
      "POST /api/timezones/activation": { status: 200, body: { changed: ["Europe/Paris"] } },
    });

    await screen.findByText("Europe/Paris");
    fireEvent.click(screen.getAllByRole("checkbox")[0] as HTMLElement);
    fireEvent.click(screen.getByRole("button", { name: "Activate" }));

    await waitFor(() => {
      const envoi = appels.find((a) => a.key.startsWith("POST"));
      expect(envoi?.body).toEqual({ slugs: ["Europe/Paris"], active: true });
    });
  });

  it("tells an empty result from an unreadable list", async () => {
    monte({ "GET /api/timezones": { status: 200, body: [] } });

    expect(await screen.findByText(/No time zone matches/i)).toBeInTheDocument();
    expect(screen.queryByText(/could not be read/i)).not.toBeInTheDocument();
  });

  it("says when the list could not be read at all", async () => {
    monte({ "GET /api/timezones": { status: 503, body: { detail: "indisponible" } } });

    expect(await screen.findByText(/could not be read/i)).toBeInTheDocument();
  });
});
