import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import "../i18n/i18n";
import type { EventsPage, JournalEvent } from "../api/events";
import i18n from "../i18n/i18n";
import { type Routes, mockApi } from "../test/mockApi";
import { EventsScreen } from "./EventsScreen";

// TYPÉS : passés en valeurs libres, un champ ajouté au contrat les laisserait muets et
// les tests resteraient verts sur un écran incomplet (leçon du 29/10/2026).
const EVENT: JournalEvent = {
  id: "11111111-1111-4111-8111-111111111111",
  type: "secret.created",
  // Une date métier DIFFÉRENTE de la date d'écriture : avec la même, aucun test ne
  // distinguerait les deux colonnes, et l'écran pourrait afficher deux fois la même
  // sans que rien ne rougisse.
  functional_at: "2026-10-28T09:00:00Z",
  functional_at_source: "caller",
  written_at: "2026-11-02T10:21:29Z",
  author_directory: "local",
  author_subject: "admin",
  properties: { slug: "pat-forge" },
  objects: [{ kind: "secret", id: "pat-forge", sequence: 1 }],
};
const DATE_D_ECRITURE: JournalEvent = {
  ...EVENT,
  id: "22222222-2222-4222-8222-222222222222",
  type: "storage.materialised",
  functional_at_source: "write_time",
  properties: {},
  objects: [],
};

function page(extra: Partial<EventsPage> = {}): EventsPage {
  return {
    events: [EVENT],
    total: 1,
    page: 1,
    size: 50,
    window: { start: "2026-10-27T12:00:00Z", end: "2026-11-03T12:00:00Z", defaulted: true },
    missing_sequences: [],
    ...extra,
  };
}

function monte(routes: Routes) {
  const calls = mockApi(routes);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <EventsScreen />
    </QueryClientProvider>,
  );
  return calls;
}

const UN_EVENT: Routes = { "GET /api/events": { status: 200, body: page() } };

describe("l'écran du journal d'events", () => {
  it("renders one row per event, with its type, author and objects", async () => {
    monte(UN_EVENT);

    // Attendu sur une valeur qui n'existe QUE chargée : le cadre, le titre et les filtres
    // sont rendus pendant l'attente, donc les y chercher tout de suite réussit sans rien
    // prouver (leçon du 02/11/2026).
    expect(await screen.findByText(/1 event\(s\)/)).toBeInTheDocument();
    const ligne = within(screen.getByRole("listitem"));
    expect(ligne.getByText("secret.created")).toBeInTheDocument();
    expect(ligne.getByText(/local\/admin/)).toBeInTheDocument();
    expect(ligne.getByText("secret/pat-forge #1")).toBeInTheDocument();
  });

  it("shows the properties without offering any filter on them", async () => {
    monte(UN_EVENT);
    expect(await screen.findByText(/1 event\(s\)/)).toBeInTheDocument();

    // Affichées…
    expect(screen.getByText("slug")).toBeInTheDocument();
    expect(screen.getByText('"pat-forge"')).toBeInTheDocument();
    // …et AUCUN champ pour les interroger : où se déclare ce qui est filtrable dans
    // `properties` n'est pas tranché (ticket 461f0cf1), et un filtre écrit ici
    // devancerait cette décision.
    const filtres = screen.getAllByRole("textbox").map((champ) => champ.getAttribute("name"));
    expect(filtres).not.toContain("properties");
    expect(screen.queryByText(/propert/i)).not.toBeInTheDocument();
  });

  it("SAYS it only showed the default window", async () => {
    monte(UN_EVENT);

    expect(await screen.findByText(/Default window/)).toBeInTheDocument();
  });

  it("stops saying « default window » once dates are given", async () => {
    monte({
      "GET /api/events": {
        status: 200,
        body: page({ window: { start: "2026-01-01T00:00:00Z", end: "2026-11-03T00:00:00Z", defaulted: false } }),
      },
    });
    expect(await screen.findByText(/1 event\(s\)/)).toBeInTheDocument();

    expect(screen.queryByText(/Default window/)).not.toBeInTheDocument();
  });

  it("marks an event whose functional date is just its write time", async () => {
    monte({
      "GET /api/events": { status: 200, body: page({ events: [DATE_D_ECRITURE] }) },
    });
    expect(await screen.findByText(/1 event\(s\)/)).toBeInTheDocument();

    expect(screen.getByText("write time")).toBeInTheDocument();
  });

  it("signals missing sequence numbers as the normal effect of purging", async () => {
    monte({
      "GET /api/events": { status: 200, body: page({ missing_sequences: [2, 3] }) },
    });

    expect(await screen.findByText(/Missing sequence numbers: 2, 3/)).toBeInTheDocument();
  });

  it("says « no event » without making it an error", async () => {
    monte({
      "GET /api/events": { status: 200, body: page({ events: [], total: 0 }) },
    });

    expect(await screen.findByText("No event in this window.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("sends the type filter and drops the empty ones", async () => {
    const calls = monte(UN_EVENT);
    expect(await screen.findByText(/1 event\(s\)/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Event type"), { target: { value: "secret.created" } });

    await waitFor(() => {
      const dernier = calls[calls.length - 1]?.key ?? "";
      expect(dernier).toContain("type=secret.created");
    });
    // Les filtres vides sont RETIRÉS : `?written_from=` filtrerait sur la chaîne vide.
    expect(calls[calls.length - 1]?.key).not.toContain("written_from=");
  });

  it("names an inverted date range instead of saying « error »", async () => {
    monte({
      "GET /api/events": {
        status: 400,
        body: { detail: { code: "bornes_inversees", detail: "written_at" } },
      },
    });

    expect(await screen.findByText(/date bounds are inverted/)).toBeInTheDocument();
  });

  it("says the journal could not be read when the reason is unknown", async () => {
    monte({ "GET /api/events": { status: 500 } });

    expect(await screen.findByText("The journal could not be read.")).toBeInTheDocument();
  });

  it("offers no pagination when everything fits on one page", async () => {
    monte(UN_EVENT);
    expect(await screen.findByText(/1 event\(s\)/)).toBeInTheDocument();

    expect(screen.queryByText(/Page 1 of/)).not.toBeInTheDocument();
  });

  it("paginates and comes back to page 1 when the filter changes", async () => {
    const calls = monte({
      "GET /api/events": { status: 200, body: page({ total: 120 }) },
    });
    expect(await screen.findByText(/120 event\(s\)/)).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Next"));
    await waitFor(() => expect(calls[calls.length - 1]?.key).toContain("page=2"));

    // Rester en page 2 d'un résultat filtré qui n'en a qu'une afficherait un journal vide
    // sans dire pourquoi.
    fireEvent.change(screen.getByLabelText("Event type"), { target: { value: "autre" } });

    await waitFor(() => {
      const dernier = calls[calls.length - 1]?.key ?? "";
      expect(dernier).toContain("page=1");
      expect(dernier).toContain("type=autre");
    });
  });

  it("writes the journal dates in the INTERFACE culture, not the browser's", async () => {
    // Forcé en français : les tests du dépôt tournent en en-US, où le défaut d'origine —
    // `toLocaleString()` sans culture — était rigoureusement invisible (bug 4f53012d).
    await i18n.changeLanguage("fr-FR");
    try {
      monte(UN_EVENT);

      expect(await screen.findByText(/1 event\(s\)/)).toBeInTheDocument();
      // 02/11, et non 11/02 : l'event a été écrit le 2 novembre. Porté sur la LIGNE :
      // la date paraît aussi dans la phrase de la fenêtre par défaut, et `getByText`
      // trouverait alors deux éléments — pour une raison sans rapport avec le défaut.
      const ligne = within(screen.getByRole("listitem"));
      expect(ligne.getByText(/02\/11\/2026/)).toBeInTheDocument();
      // Et la date FONCTIONNELLE, dans la même culture : les deux colonnes passent par
      // le même point de formatage.
      expect(ligne.getByText(/28\/10\/2026/)).toBeInTheDocument();
    } finally {
      await act(() => i18n.changeLanguage("en-US"));
    }
  });
});
