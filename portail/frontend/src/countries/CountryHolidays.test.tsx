import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { render, screen } from "@testing-library/react";

import type { CountryHolidays as Regles } from "../api/countries";
import { CountryHolidays } from "./CountryHolidays";
import "../i18n/i18n";

// Les jours fériés vus depuis un pays (Gael, 11/11/2026) : le LIEN vers le fichier de
// règles du dépôt calendarium, et les JOURS que ces règles produisent sur douze mois.
//
// Le jeu d'essai est TYPÉ : un `unknown` dans un harnais est un compilateur qu'on a
// éteint, et l'ajout d'un champ au contrat passerait inaperçu jusqu'au rendu.

const RAW =
  "https://raw.githubusercontent.com/gaelgael5/calendarium/main" +
  "/src/calendarium/data/countries/date_France.json";
const PAGE =
  "https://github.com/gaelgael5/calendarium/blob/main" +
  "/src/calendarium/data/countries/date_France.json";

const REGLES: Regles = {
  country: "France",
  source_url: RAW,
  page_url: PAGE,
  start: "2026-11-11",
  end: "2027-11-11",
  days: [
    // Trois jours qui ne se ressemblent pas : un ordinaire, un REPORTÉ, un NON chômé.
    // Trois lignes identiques laisseraient passer une pastille rendue pour tout le monde.
    { date: "2026-12-25", observed: "2026-12-25", name: "Christmas Day", free: true, shifted: false },
    { date: "2027-01-01", observed: "2027-01-04", name: "New Year's Day", free: true, shifted: true },
    { date: "2027-05-08", observed: "2027-05-08", name: "Victory Day", free: false, shifted: false },
  ],
};

function monte(routes: Routes) {
  const appels = mockApi(routes);
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CountryHolidays countrySlug="FRA" />
    </QueryClientProvider>,
  );
  return appels;
}

describe("jours fériés d'un pays", () => {
  it("links to the GitHub PAGE, not to the raw file, and names the file", async () => {
    monte({ "GET /api/countries/FRA/holidays": { status: 200, body: REGLES } });

    const lien = await screen.findByRole("link", { name: /date_France\.json/ });
    // La page navigable : c'est ce que Gael a demandé — « pouvoir cliquer dessus pour
    // aller sur le site github, sur la page ». L'URL brute rendrait du texte nu.
    expect(lien).toHaveAttribute("href", PAGE);
    // L'URL complète reste lisible en infobulle : c'est elle que la base porte.
    expect(lien).toHaveAttribute("title", RAW);
    expect(lien).toHaveAttribute("target", "_blank");
    expect(lien.getAttribute("rel")).toContain("noreferrer");
  });

  it("announces the window the SERVER computed, not one of its own", async () => {
    monte({ "GET /api/countries/FRA/holidays": { status: 200, body: REGLES } });

    // Les douze mois, dans la culture de l'interface (en-US par convention de test).
    expect(
      await screen.findByText(/November 11, 2026.*November 11, 2027/),
    ).toBeInTheDocument();
  });

  it("shows each computed day with its name", async () => {
    monte({ "GET /api/countries/FRA/holidays": { status: 200, body: REGLES } });

    expect(await screen.findByText("Christmas Day")).toBeInTheDocument();
    expect(screen.getByText(/December 25, 2026/)).toBeInTheDocument();
  });

  it("tells a day off from a day that is NOT one", async () => {
    // Une commémoration calculée sans être un congé serait lue comme une fermeture, et un
    // point relais fermerait pour rien.
    monte({ "GET /api/countries/FRA/holidays": { status: 200, body: REGLES } });

    expect(await screen.findAllByText("Day off")).toHaveLength(2);
    expect(screen.getByText("Not a day off")).toBeInTheDocument();
  });

  it("says WHERE a holiday is observed only when it is shifted", async () => {
    monte({ "GET /api/countries/FRA/holidays": { status: 200, body: REGLES } });

    expect(await screen.findByText(/Observed on.*January 4, 2027/)).toBeInTheDocument();
    // Et une seule fois : écrire le report d'un jour qui n'en a pas ferait douter de ce
    // que la ligne annonce.
    expect(screen.getAllByText(/Observed on/)).toHaveLength(1);
  });

  it("says plainly when the twelve months hold no holiday at all", async () => {
    monte({
      "GET /api/countries/FRA/holidays": { status: 200, body: { ...REGLES, days: [] } },
    });

    expect(await screen.findByText(/No public holiday computed/)).toBeInTheDocument();
  });

  it("distinguishes a VERSION mismatch from a plain read failure", async () => {
    // `regles_indisponibles` : la base associe un fichier que le paquet installé ne porte
    // pas. Le geste est d'aller regarder la version de calendarium, et le message
    // générique n'enverrait nulle part.
    monte({
      "GET /api/countries/FRA/holidays": {
        status: 409,
        body: { detail: { country: "France" }, reason: "regles_indisponibles" },
      },
    });

    expect(await screen.findByText(/installed engine does not carry them/)).toBeInTheDocument();
  });

  it("falls back to the plain message for any other failure", async () => {
    monte({ "GET /api/countries/FRA/holidays": { status: 500, body: {} } });

    expect(await screen.findByText(/could not be read/)).toBeInTheDocument();
  });
});
