import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { Country } from "../api/countries";
import type { Timezone } from "../api/timezones";
import { CountriesScreen } from "./CountriesScreen";
import "../i18n/i18n";

// L'association vue depuis le pays (story 2ae7e357). Ce qui est éprouvé ici est ce que
// cette story ajoute : le dépli à la demande, et le fait que l'écran DISE que l'activation
// est globale. Le reste — la liste, le filtre, l'activation groupée — est éprouvé par
// `CountriesScreen.test.tsx`.

const LUXEMBOURG: Country = { slug: "LUX", alpha2: "LU", label: "Luxembourg", active: true };
const FRANCE: Country = { slug: "FRA", alpha2: "FR", label: "France", active: true };

// Trois pays pour une zone : c'est le cas qui justifie l'avertissement.
const BRUXELLES: Timezone = {
  slug: "Europe/Brussels",
  label: "Central European Time",
  countries: ["BEL", "LUX", "NLD"],
  active: false,
};
// Un seul pays : la moitié discriminante, sans quoi le test ne prouverait pas que
// l'avertissement dépend du partage.
const PARIS: Timezone = {
  slug: "Europe/Paris",
  label: "Central European Time",
  countries: ["FRA"],
  active: true,
};

function monte(routes: Routes) {
  const appels = mockApi(routes);
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CountriesScreen />
    </QueryClientProvider>,
  );
  return appels;
}

const PAYS = { "GET /api/countries": { status: 200, body: [FRANCE, LUXEMBOURG] } };

describe("les fuseaux d'un pays, dépliés depuis l'écran des pays", () => {
  it("reads nothing until a country is expanded", async () => {
    // 249 pays dépliés d'office feraient 249 lectures pour une information que personne ne
    // regarde : le panneau ne se monte que sur le geste.
    const appels = monte({ ...PAYS, "GET /api/timezones": { status: 200, body: [PARIS] } });

    await screen.findByText("FRA");

    expect(appels.some((a) => a.key.includes("/api/timezones"))).toBe(false);
  });

  it("reads the zones OF THAT COUNTRY when expanded", async () => {
    const appels = monte({ ...PAYS, "GET /api/timezones": { status: 200, body: [PARIS] } });

    await screen.findByText("FRA");
    fireEvent.click(screen.getAllByRole("button", { name: "Time zones" })[0] as HTMLElement);

    await waitFor(() => {
      expect(appels.some((a) => a.key.includes("country=FRA"))).toBe(true);
    });
    expect(await screen.findByText("Europe/Paris")).toBeInTheDocument();
    expect(screen.getByText("Retained")).toBeInTheDocument();
  });

  it("names the OTHER countries a shared zone serves, where the gesture is made", async () => {
    // Le vrai risque de cet écran : croire qu'activer un fuseau depuis le Luxembourg est
    // un geste local. L'avertissement est sur la ligne, pas en bas de page.
    monte({ ...PAYS, "GET /api/timezones": { status: 200, body: [BRUXELLES] } });

    await screen.findByText("LUX");
    fireEvent.click(screen.getAllByRole("button", { name: "Time zones" })[1] as HTMLElement);

    const avertissement = await screen.findByText(/also serves: BEL, NLD/i);
    expect(avertissement).toBeInTheDocument();
    expect(avertissement.textContent).toMatch(/retains it for those countries too/i);
  });

  it("says nothing of the kind for a zone that serves one country only", async () => {
    monte({ ...PAYS, "GET /api/timezones": { status: 200, body: [PARIS] } });

    await screen.findByText("FRA");
    fireEvent.click(screen.getAllByRole("button", { name: "Time zones" })[0] as HTMLElement);

    expect(await screen.findByText("Europe/Paris")).toBeInTheDocument();
    expect(screen.queryByText(/also serves/i)).not.toBeInTheDocument();
  });

  it("retains a zone in ONE gesture, on the shared state", async () => {
    // Une bascule directe : un pays a le plus souvent un seul fuseau, et « cocher puis
    // appliquer » demanderait deux gestes pour un élément unique.
    const appels = monte({
      ...PAYS,
      "GET /api/timezones": { status: 200, body: [BRUXELLES] },
      "POST /api/timezones/activation": { status: 200, body: { changed: ["Europe/Brussels"] } },
    });

    await screen.findByText("LUX");
    fireEvent.click(screen.getAllByRole("button", { name: "Time zones" })[1] as HTMLElement);
    await screen.findByText("Europe/Brussels");
    fireEvent.click(screen.getByRole("checkbox", { name: /Europe\/Brussels/ }));

    await waitFor(() => {
      const envoi = appels.find((a) => a.key.startsWith("POST /api/timezones"));
      expect(envoi?.body).toEqual({ slugs: ["Europe/Brussels"], active: true });
    });
  });

  it("lets a retained zone be released from the country too", async () => {
    const appels = monte({
      ...PAYS,
      "GET /api/timezones": { status: 200, body: [PARIS] },
      "POST /api/timezones/activation": { status: 200, body: { changed: ["Europe/Paris"] } },
    });

    await screen.findByText("FRA");
    fireEvent.click(screen.getAllByRole("button", { name: "Time zones" })[0] as HTMLElement);
    await screen.findByText("Europe/Paris");
    fireEvent.click(screen.getByRole("checkbox", { name: /Europe\/Paris/ }));

    await waitFor(() => {
      const envoi = appels.find((a) => a.key.startsWith("POST /api/timezones"));
      expect(envoi?.body).toEqual({ slugs: ["Europe/Paris"], active: false });
    });
  });

  it("says the state is shared with the time zones screen", async () => {
    // Sans cette phrase, un administrateur croirait tenir deux listes séparées.
    monte({ ...PAYS, "GET /api/timezones": { status: 200, body: [PARIS] } });

    await screen.findByText("FRA");
    fireEvent.click(screen.getAllByRole("button", { name: "Time zones" })[0] as HTMLElement);

    expect(await screen.findByText(/it is the same state/i)).toBeInTheDocument();
  });

  it("names a panel that could not be read", async () => {
    monte({ ...PAYS, "GET /api/timezones": { status: 503, body: { detail: "indisponible" } } });

    await screen.findByText("FRA");
    fireEvent.click(screen.getAllByRole("button", { name: "Time zones" })[0] as HTMLElement);

    expect(await screen.findByText(/could not be read/i)).toBeInTheDocument();
  });
});
