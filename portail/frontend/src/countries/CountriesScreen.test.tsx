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

// `has_holidays` DIFFÈRE d'un pays à l'autre, et c'est volontaire : un jeu d'essai qui
// porterait la même valeur partout laisserait passer une pastille affichée pour tout le
// monde, ou pour personne (leçon du dépôt sur les jeux d'essai non discriminants).
const FRANCE: Country = {
  slug: "FRA",
  alpha2: "FR",
  label: "France",
  active: false,
  has_holidays: true,
};
const ALLEMAGNE: Country = {
  slug: "DEU",
  alpha2: "DE",
  label: "Germany",
  active: true,
  has_holidays: false,
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

  it("DIT dans la liste quels pays ont des règles de jours fériés", async () => {
    // Ce que Gael a demandé le 11/11/2026 : l'association doit se voir depuis l'IHM. Sans
    // cette pastille il faudrait ouvrir 249 pays pour savoir lesquels en ont un.
    monte({ "GET /api/countries": { status: 200, body: [ALLEMAGNE, FRANCE] } });

    expect(await screen.findByText("DEU")).toBeInTheDocument();
    // La France en a, l'Allemagne non : UNE pastille, pas deux, pas zéro.
    expect(screen.getAllByText("Public holidays")).toHaveLength(2);
  });

  it("n'offre le panneau des jours fériés QUE pour un pays qui a des règles", async () => {
    // Offrir un panneau qui ne pourrait dire que « aucune règle » ferait cliquer 138 fois
    // pour rien.
    const appels = monte({
      "GET /api/countries": { status: 200, body: [ALLEMAGNE, FRANCE] },
      "GET /api/countries/FRA/holidays": {
        status: 200,
        body: {
          country: "France",
          source_url: "https://raw.githubusercontent.com/o/r/main/date_France.json",
          page_url: "https://github.com/o/r/blob/main/date_France.json",
          start: "2026-11-11",
          end: "2027-11-11",
          days: [],
        },
      },
    });

    expect(await screen.findAllByRole("button", { name: "Public holidays" })).toHaveLength(1);

    // `getByRole` au singulier : il échoue de lui-même s'il y en avait deux, là où un
    // index aurait cliqué le premier sans rien dire du second.
    fireEvent.click(screen.getByRole("button", { name: "Public holidays" }));

    // Le panneau ne se monte qu'au dépli : avant le clic, aucune lecture n'a eu lieu.
    await waitFor(() =>
      expect(appels.some((a) => a.key.includes("/api/countries/FRA/holidays"))).toBe(true),
    );
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
