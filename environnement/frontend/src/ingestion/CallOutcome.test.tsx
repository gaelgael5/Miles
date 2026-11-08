import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import { type Routes, mockApi } from "@miles/socle-web/testing";

import "../i18n/i18n";
import type { CallOutcome as Issue } from "../api/ingestion";
import { CallOutcome } from "./CallOutcome";

const INGESTION = "6ec6411a12da42c58b2d4d1485478a23";
const ROUTE = `GET /api/ingestion/calls/${INGESTION}`;

// TYPÉ : un champ ajouté au contrat laisserait un jeu d'essai libre muet, et le test
// resterait vert sur un écran incomplet (leçon du 29/10/2026).
const ISSUE: Issue = {
  id: INGESTION,
  state: "traite",
  // Les quatre instants d'un import réel : deux secondes d'attente, une minute
  // cinquante et une de lecture, dix-neuf secondes d'écriture. DISCRIMINANTS — avec des
  // durées égales, rien ne distinguerait les trois phases l'une de l'autre.
  received_at: "2026-11-08T18:24:38Z",
  started_at: "2026-11-08T18:24:40Z",
  apply_started_at: "2026-11-08T18:26:31Z",
  finished_at: "2026-11-08T18:26:50Z",
  items_read: 194361,
  failure_code: null,
  failure_detail: null,
  received: 194361,
  written: 151007,
  unchanged: 17768,
  rejected: 25586,
  reasons: [
    {
      reason: "modele_non_respecte",
      detail: "$['Contact']['Email']: None is not of type 'string'",
      count: 25102,
      sample_key: '["IT10002"]',
    },
    {
      reason: "modele_non_respecte",
      detail: "$['Country']: None is not of type 'string'",
      count: 484,
      sample_key: null,
    },
  ],
  anomalies: ["detail_plafonne:200"],
};

function monte(issue: Partial<Issue> = {}) {
  const routes: Routes = { [ROUTE]: { status: 200, body: { ...ISSUE, ...issue } } };
  const calls = mockApi(routes);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CallOutcome ingestionId={INGESTION} />
    </QueryClientProvider>,
  );
  return calls;
}

describe("le compte-rendu d'un dépôt", () => {
  it("rend chaque MOTIF de rejet avec son compte et un exemple", async () => {
    monte();

    // Le motif porte le chemin de l'écart : c'est ce qui permet de corriger le modèle
    // sans appel exploratoire.
    expect(
      await screen.findByText("$['Contact']['Email']: None is not of type 'string'"),
    ).toBeInTheDocument();
    expect(screen.getByText("25,102")).toBeInTheDocument();
    expect(screen.getByText("484")).toBeInTheDocument();
    // Les deux motifs ont la même raison : c'est le DÉTAIL qui les distingue, et deux
    // lignes doivent sortir — une synthèse qui les regrouperait ne dirait plus quoi
    // corriger.
    expect(screen.getAllByText(/model not satisfied/)).toHaveLength(2);
    expect(screen.getByText(/\["IT10002"\]/)).toBeInTheDocument();
  });

  it("sépare les comptes, qui portent le résultat de l'import", async () => {
    monte();

    expect(
      await screen.findByText("151,007 written · 17,768 unchanged · 25,586 rejected"),
    ).toBeInTheDocument();
  });

  it("sépare les TROIS temps de l'import, qui ne se confondent pas", async () => {
    // Un seul nombre ferait chercher une lenteur au mauvais endroit : l'attente en file
    // ne dit rien du coût du document, la lecture est le temps long, et l'écriture est
    // celle qui tient une transaction.
    monte();

    expect(await screen.findByText(/2 min 10 sec/)).toBeInTheDocument();
    expect(screen.getByText(/reading 1 min 51 sec/)).toBeInTheDocument();
    expect(screen.getByText(/writing 19 sec/)).toBeInTheDocument();
    expect(screen.getByText("Queued before start: 2 sec")).toBeInTheDocument();
  });

  it("ne montre AUCUNE durée pour un mode synchrone, qui traite dans l'appel", async () => {
    // Les instants de l'import sont nuls : afficher « 0 s » ferait croire à un import
    // instantané là où il n'y a pas eu d'import du tout.
    monte({ started_at: null, apply_started_at: null, finished_at: null, items_read: null });

    expect(await screen.findByText(/written/)).toBeInTheDocument();
    expect(screen.queryByText(/Import:/)).not.toBeInTheDocument();
  });

  it("dit qu'AUCUN objet n'a été rejeté plutôt que de ne rien dire", async () => {
    // Un écran muet se lit comme un écran qui n'a pas chargé.
    monte({ reasons: [], rejected: 0, anomalies: [] });

    expect(await screen.findByText("No object rejected.")).toBeInTheDocument();
  });

  it("nomme l'arrêt d'un import interrompu", async () => {
    monte({ state: "incomplet", failure_code: "document_json_invalide", failure_detail: "ligne 44" });

    expect(await screen.findByText(/document_json_invalide/)).toBeInTheDocument();
    expect(screen.getByText(/ligne 44/)).toBeInTheDocument();
  });

  it("distingue un compte-rendu ILLISIBLE d'un dépôt sans rejet", async () => {
    // Les confondre ferait conclure que tout est passé au pire moment pour le conclure.
    mockApi({});
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <CallOutcome ingestionId={INGESTION} />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This deposit's report could not be read.",
    );
  });
});
