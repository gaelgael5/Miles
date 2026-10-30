import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { Country } from "../api/countries";
import { CountriesScreen } from "./CountriesScreen";
import "../i18n/i18n";

// L'écran des pays : un référentiel DONNÉ, où l'on n'active et ne désactive que.
//
// Les jeux d'essai sont TYPÉS : un `unknown[]` dans un harnais est un compilateur qu'on a
// éteint, et l'ajout d'un champ au contrat passerait inaperçu jusqu'au rendu (leçon du
// 29/10/2026).

const FRANCE: Country = { slug: "FRA", alpha2: "FR", label: "France", active: false };
const ALLEMAGNE: Country = { slug: "DEU", alpha2: "DE", label: "Germany", active: true };

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

describe("écran des pays", () => {
  it("shows each country with its label first, then its two codes", async () => {
    monte({ "GET /api/countries": { status: 200, body: [ALLEMAGNE, FRANCE] } });

    // Le libellé est ce qu'on cherche, les codes ce qu'on recopie : les deux sont là.
    expect(await screen.findByText("DEU")).toBeInTheDocument();
    expect(screen.getByText("FR")).toBeInTheDocument();
    expect(screen.getByText(/Germany/)).toBeInTheDocument();
    // Seul l'actif porte la pastille.
    expect(screen.getAllByText("Active")).toHaveLength(1);
  });

  it("says the list is given and that deactivating deletes nothing", async () => {
    // Ce n'est pas de la décoration : un administrateur qui croit perdre quelque chose en
    // désactivant ne désactive pas, et se met à chercher une autre voie.
    monte({ "GET /api/countries": { status: 200, body: [FRANCE] } });

    expect(await screen.findByText(/comes from ISO 3166 and cannot be edited/i)).toBeInTheDocument();
    expect(screen.getByText(/does not delete it/i)).toBeInTheDocument();
  });

  it("sends the filter TO THE SERVER, with the culture of the screen", async () => {
    // Le serveur dérive les libellés : lui seul peut faire correspondre « germany » à DEU.
    // Refaire le filtre ici donnerait deux implémentations, dont une aveugle aux libellés.
    const appels = monte({ "GET /api/countries": { status: 200, body: [ALLEMAGNE] } });

    await screen.findByText("DEU");
    fireEvent.change(screen.getByLabelText("Filter by name or code"), {
      target: { value: "germany" },
    });

    await waitFor(() => {
      expect(appels.some((a) => a.key.includes("q=germany"))).toBe(true);
    });
    expect(appels.every((a) => a.key.includes("culture="))).toBe(true);
  });

  it("activates exactly what is checked, not what is displayed", async () => {
    const appels = monte({
      "GET /api/countries": { status: 200, body: [FRANCE, ALLEMAGNE] },
      "POST /api/countries/activation": { status: 200, body: { changed: ["FRA"] } },
    });

    await screen.findByText("FRA");
    fireEvent.click(screen.getAllByRole("checkbox")[0] as HTMLElement);
    fireEvent.click(screen.getByRole("button", { name: "Activate" }));

    await waitFor(() => {
      const envoi = appels.find((a) => a.key.startsWith("POST"));
      expect(envoi?.body).toEqual({ slugs: ["FRA"], active: true });
    });
  });

  it("refuses to act when nothing is checked", async () => {
    // Un geste qui ne porte sur rien n'est pas un geste : les deux boutons restent éteints.
    monte({ "GET /api/countries": { status: 200, body: [FRANCE] } });

    await screen.findByText("FRA");

    expect(screen.getByRole("button", { name: "Activate" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Deactivate" })).toBeDisabled();
  });

  it("names a refused change instead of leaving the screen silent", async () => {
    monte({
      "GET /api/countries": { status: 200, body: [FRANCE] },
      "POST /api/countries/activation": {
        status: 422,
        body: { detail: { field: "slugs", unknown: ["XYZ"] } },
      },
    });

    await screen.findByText("FRA");
    fireEvent.click(screen.getAllByRole("checkbox")[0] as HTMLElement);
    fireEvent.click(screen.getByRole("button", { name: "Activate" }));

    expect(await screen.findByText(/change was refused/i)).toBeInTheDocument();
  });

  it("tells an empty result from an unreadable list", async () => {
    // Deux états qui ne se lisent pas pareil : « aucun pays ne correspond » attend qu'on
    // change le filtre, « la liste n'a pas pu être lue » attend autre chose.
    monte({ "GET /api/countries": { status: 200, body: [] } });

    expect(await screen.findByText(/No country matches/i)).toBeInTheDocument();
    expect(screen.queryByText(/could not be read/i)).not.toBeInTheDocument();
  });

  it("says when the list could not be read at all", async () => {
    monte({ "GET /api/countries": { status: 503, body: { detail: "indisponible" } } });

    expect(await screen.findByText(/could not be read/i)).toBeInTheDocument();
  });
});
