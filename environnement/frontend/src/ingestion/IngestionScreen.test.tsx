import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { type Routes, mockApi } from "@miles/socle-web/testing";

import "../i18n/i18n";
import type { Call, Health } from "../api/ingestion";
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
const FICHIER = {
  source: "comptes-pudo",
  storage: "accounts",
  entry_model: "pudo/accounts",
  mode: "fichier",
  path: "/ingest/comptes-pudo/fichier",
  served: false,
};
const APPEL: Call = {
  id: "a".repeat(32),
  source: "comptes-pudo",
  mode: "tableau",
  entry_model: "pudo/accounts",
  object_count: 42,
  size_bytes: 1337,
  version_number: 4,
  key_label: "Transporteur",
  key_prefix: "mlk_kkkkkkkk",
  received_at: "2026-11-02T09:30:00Z",
  state: "recu",
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

const VIDE: Routes = {
  "GET /api/ingestion/calls": {
    status: 200,
    body: { calls: [], total: 0, page: 1, page_size: 50, sources: ["comptes-pudo", "sites-pudo"] },
  },
};
const UN_APPEL: Routes = {
  "GET /api/ingestion/health": { status: 200, body: SERVIE },
  "GET /api/ingestion/calls": {
    status: 200,
    body: {
      calls: [APPEL],
      total: 1,
      page: 1,
      page_size: 50,
      sources: ["comptes-pudo", "sites-pudo"],
    },
  },
};

describe("l'écran du service d'ingestion", () => {
  it("montre la version servie, les clés et les dépôts", async () => {
    monte(UN_APPEL);

    expect(await screen.findByText(/Version 4/)).toBeInTheDocument();
    // Le commit est tronqué : les douze premiers caractères suffisent à le reconnaître.
    expect(screen.getByText(/abcdef123456/)).toBeInTheDocument();
    expect(screen.getByText(/2 active key\(s\), 1 never used/)).toBeInTheDocument();
    expect(screen.getByText(/7 deposit\(s\) received, 3 in the last 24h/)).toBeInTheDocument();
  });

  it("donne l'adresse complète de chaque point d'entrée, et ce qu'elle alimente", async () => {
    // C'est la seule façon de répondre à « où est-ce que je pousse ? » sans faire lire
    // un fichier de paramétrage.
    monte(UN_APPEL);

    expect(await screen.findByText("/ingest/comptes-pudo/tableau")).toBeInTheDocument();
    expect(screen.getByText("pudo/accounts")).toBeInTheDocument();
    expect(screen.getByText("accounts")).toBeInTheDocument();
  });

  it("dit qu'aucune version n'est servie, plutôt que de rendre un écran vide", async () => {
    monte({
      ...VIDE,
      "GET /api/ingestion/health": {
        status: 200,
        body: { ...SERVIE, version_number: null, version_commit: null, endpoints: [] },
      },
    });

    expect(await screen.findByText(/No configuration version is served/)).toBeInTheDocument();
    // L'état normal d'une stack neuve : aucune alerte.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("distingue un mode déclaré mais pas encore servi", async () => {
    // L'afficher comme disponible promettrait un dépôt qui sera refusé.
    monte({
      ...VIDE,
      "GET /api/ingestion/health": {
        status: 200,
        body: {
          ...SERVIE,
          endpoints: [FICHIER],
          bulk_modes: ["fichier"],
        },
      },
    });

    expect(await screen.findByText(/declared but not served yet/)).toBeInTheDocument();
  });

  it("ne met AUCUN compteur sur une file qui n'existe pas", async () => {
    // « pas encore servi » est une information ; « 0 en attente » est un mensonge.
    monte({
      ...VIDE,
      "GET /api/ingestion/health": { status: 200, body: { ...SERVIE, bulk_modes: ["fichier"] } },
    });

    expect(await screen.findByText(/there is no queue to watch/)).toBeInTheDocument();
    expect(screen.queryByText(/0 pending/)).not.toBeInTheDocument();
  });

  it("nomme les sources déclarées mais illisibles", async () => {
    monte({
      ...VIDE,
      "GET /api/ingestion/health": {
        status: 200,
        body: { ...SERVIE, unreadable_sources: ["cassee"] },
      },
    });

    expect(await screen.findByText(/unreadable: cassee/)).toBeInTheDocument();
  });

  it("rend une ligne par appel, avec le préfixe de la clé et jamais sa valeur", async () => {
    monte(UN_APPEL);

    // Attendu sur une valeur qui n'existe QUE chargée : la section et son filtre sont
    // rendus pendant l'attente, donc les y chercher tout de suite réussit sans rien
    // prouver — et l'assertion suivante échouerait pour une raison sans rapport.
    expect(await screen.findByText("1 call(s)")).toBeInTheDocument();
    const journal = within(screen.getByRole("region", { name: "Recent calls" }));
    expect(journal.getByText(/42 object\(s\)/)).toBeInTheDocument();
    expect(journal.getByText(/1337 bytes/)).toBeInTheDocument();
    expect(journal.getByText(/by Transporteur \(mlk_kkkkkkkk\)/)).toBeInTheDocument();
    expect(journal.getByText(/received/)).toBeInTheDocument();
  });

  it("dit « aucun appel » sans en faire une erreur", async () => {
    monte({ "GET /api/ingestion/health": { status: 200, body: SERVIE }, ...VIDE });

    expect(await screen.findByText("No call received.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("distingue une lecture en échec d'un journal vide", async () => {
    // Les confondre ferait conclure que tout va bien au pire moment pour le conclure.
    monte({
      "GET /api/ingestion/health": { status: 200, body: SERVIE },
      "GET /api/ingestion/calls": { status: 500, body: {} },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be read");
    expect(screen.queryByText("No call received.")).not.toBeInTheDocument();
  });

  it("n'offre en filtre que les sources de la version servie", async () => {
    monte(UN_APPEL);
    // Chargé d'abord : les sources viennent de la réponse du journal, et le filtre est
    // rendu avant elle.
    await screen.findByText("1 call(s)");
    const filtre = within(screen.getByRole("form", { name: "Journal filter" }));

    const proposees = filtre
      .getAllByRole<HTMLOptionElement>("option")
      .map((option) => option.value);

    expect(proposees).toEqual(["", "comptes-pudo", "sites-pudo"]);
  });

  it("restreint le journal à une source et revient à la première page", async () => {
    // Rester en page 3 d'un journal qui n'en a plus qu'une afficherait un vide qu'on
    // prendrait pour « ce partenaire n'a rien déposé ». Éprouvé en allant d'abord à la
    // page 2 : sans ce détour, l'assertion « page=1 » serait vraie sans rien prouver.
    const calls = monte({
      "GET /api/ingestion/health": { status: 200, body: SERVIE },
      "GET /api/ingestion/calls": {
        status: 200,
        body: {
          calls: [APPEL],
          total: 120,
          page: 1,
          page_size: 50,
          sources: ["comptes-pudo", "sites-pudo"],
        },
      },
    });
    const filtre = () => within(screen.getByRole("form", { name: "Journal filter" }));
    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();

    fireEvent.change(filtre().getByLabelText("Source"), { target: { value: "sites-pudo" } });

    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.map((c) => c.key)).toContain(
        "GET /api/ingestion/calls?page=1&source=sites-pudo",
      ),
    );
  });

  it("dit que l'état du service n'a pas pu être lu", async () => {
    monte({ ...VIDE, "GET /api/ingestion/health": { status: 500, body: {} } });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "ingestion service state could not be read",
    );
  });
});
