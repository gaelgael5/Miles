import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen } from "@testing-library/react";

import "../i18n/i18n";

import { ConnexionsConfiees } from "./ConnexionsConfiees";

// Ce que le module de paramétrage tient en PLUS d'un pair : les connexions git qu'il lui
// confie. Trois états qui ne se lisent pas pareil, et c'est la raison de ce composant —
// « transmis et à jour », « jamais transmis » et « transmis mais périmé » appellent trois
// lectures différentes, et la troisième est celle qui n'existerait pas si l'écran se
// contentait d'une date.

const ETAT = "GET /api/git-connections/confided";

function monte(routes: Routes) {
  mockApi(routes);
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <ConnexionsConfiees />
    </QueryClientProvider>,
  );
}

describe("connexions git confiées", () => {
  it("shows how many connections are held, and when they were handed over", async () => {
    monte({
      [ETAT]: {
        status: 200,
        body: {
          peer_base_url: "http://enrolement",
          revision: 4,
          transmitted_at: "2026-10-30T08:00:00+00:00",
          up_to_date: true,
          connections: 2,
        },
      },
    });

    expect(await screen.findByText("2 connections")).toBeInTheDocument();
    expect(screen.getByText("revision 4")).toBeInTheDocument();
    // Rien à réparer : aucun avertissement n'est affiché à tort.
    expect(screen.queryByText(/no longer holds what we have/i)).not.toBeInTheDocument();
  });

  it("says nothing has been handed over yet, which is not a failure", async () => {
    monte({
      [ETAT]: {
        status: 200,
        body: {
          peer_base_url: "http://enrolement",
          revision: null,
          transmitted_at: null,
          up_to_date: false,
          connections: 1,
        },
      },
    });

    expect(await screen.findByText(/Nothing has been handed/i)).toBeInTheDocument();
    expect(screen.queryByText(/no longer holds what we have/i)).not.toBeInTheDocument();
  });

  it("names the divergence when the peer holds an older version", async () => {
    // Le cas qui n'existerait pas sans `up_to_date` : une date de transmission EST là, et
    // l'écran dirait « confiées » pour une photo que l'autre bout n'a plus.
    monte({
      [ETAT]: {
        status: 200,
        body: {
          peer_base_url: "http://enrolement",
          revision: 2,
          transmitted_at: "2026-10-30T08:00:00+00:00",
          up_to_date: false,
          connections: 3,
        },
      },
    });

    expect(await screen.findByText(/no longer holds what we have/i)).toBeInTheDocument();
  });

  it("surfaces a refused transmission instead of swallowing it", async () => {
    // Le geste est demandé par une PERSONNE : contrairement aux déclencheurs
    // automatiques, il doit dire pourquoi ça ne passe pas.
    monte({
      [ETAT]: {
        status: 200,
        body: {
          peer_base_url: "http://enrolement",
          revision: 2,
          transmitted_at: "2026-10-30T08:00:00+00:00",
          up_to_date: false,
          connections: 1,
        },
      },
      "POST /api/git-connections/confided": {
        status: 409,
        body: { detail: { code: "refusee", peer_detail: "revision_depassee" } },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Send again now" }));

    expect(await screen.findByText(/transmission was refused/i)).toBeInTheDocument();
  });
});
