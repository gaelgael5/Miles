import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { type Routes, mockApi } from "@miles/socle-web/testing";

import "../i18n/i18n";
import type { Health } from "../api/ingestion";
import { IngestionScreen } from "./IngestionScreen";

const SERVIE: Health = {
  version_number: 4,
  version_commit: "abcdef1234567890",
  version_served_at: "2026-11-02T08:00:00Z",
  endpoints: [
    {
      source: "comptes-pudo",
      storage: "accounts",
      entry_model: "pudo/accounts",
      mode: "tableau",
      path: "/ingest/comptes-pudo/tableau",
      served: true,
    },
  ],
  unreadable_sources: [],
  active_keys: 2,
  never_used_keys: 1,
  deposits_total: 7,
  deposits_recent: 3,
  last_deposit_at: "2026-11-02T09:30:00Z",
  bulk_modes: [],
};

function monte(routes: Routes) {
  const calls = mockApi(routes);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <IngestionScreen />
    </QueryClientProvider>,
  );
  return calls;
}

const EN_SERVICE: Routes = { "GET /api/ingestion/health": { status: 200, body: SERVIE } };

describe("l'écran du service d'ingestion", () => {
  it("montre la version servie, les clés et les dépôts", async () => {
    monte(EN_SERVICE);

    // La version est une VALEUR sous son étiquette (Gael, 05/11/2026), et plus une
    // phrase en capitales : l'étiquette porte le mot, la valeur porte le nombre.
    expect(await screen.findByText("Served version")).toBeInTheDocument();
    // Le commit est tronqué : les douze premiers caractères suffisent à le reconnaître.
    expect(screen.getByText(/4 · commit abcdef123456/)).toBeInTheDocument();
    expect(screen.getByText(/2 active key\(s\), 1 never used/)).toBeInTheDocument();
    expect(screen.getByText(/7 deposit\(s\) received, 3 in the last 24h/)).toBeInTheDocument();
  });

  it("ne demande que l'état du service : les méthodes et le journal sont à la source", async () => {
    // La garde du découpage du 04/11/2026. Sans elle, une page de service qui
    // continuerait d'interroger les méthodes de TOUTES les sources passerait inaperçue :
    // elle n'afficherait rien de plus, et paierait une requête par ouverture.
    const calls = monte(EN_SERVICE);

    expect(await screen.findByText("Served version")).toBeInTheDocument();
    expect(calls.map((appel) => appel.key)).toEqual(["GET /api/ingestion/health"]);
  });

  it("dit qu'aucune version n'est servie, plutôt que de rendre un écran vide", async () => {
    monte({
      "GET /api/ingestion/health": {
        status: 200,
        body: { ...SERVIE, version_number: null, version_commit: null, endpoints: [] },
      },
    });

    expect(await screen.findByText(/No configuration version is served/)).toBeInTheDocument();
    // L'état normal d'une stack neuve : aucune alerte.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("ne met AUCUN compteur sur une file qui n'existe pas", async () => {
    // « pas encore servi » est une information ; « 0 en attente » est un mensonge.
    monte({
      "GET /api/ingestion/health": { status: 200, body: { ...SERVIE, bulk_modes: ["fichier"] } },
    });

    expect(await screen.findByText(/there is no queue to watch/)).toBeInTheDocument();
    expect(screen.queryByText(/0 pending/)).not.toBeInTheDocument();
  });

  it("nomme les sources déclarées mais illisibles", async () => {
    monte({
      "GET /api/ingestion/health": {
        status: 200,
        body: { ...SERVIE, unreadable_sources: ["cassee"] },
      },
    });

    expect(await screen.findByText(/unreadable: cassee/)).toBeInTheDocument();
  });

  it("dit que l'état du service n'a pas pu être lu", async () => {
    monte({ "GET /api/ingestion/health": { status: 500, body: {} } });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "ingestion service state could not be read",
    );
  });
});
