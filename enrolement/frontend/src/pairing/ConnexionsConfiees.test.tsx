import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen } from "@testing-library/react";

import type { ConfidedGitState } from "../api/confiedGit";
import { ConnexionsConfiees } from "./ConnexionsConfiees";
import "../i18n/i18n";

// Ce que ce module DÉTIENT pour le compte du module de paramétrage (ticket edcf78bc).
//
// Les jeux d'essai sont TYPÉS : jusqu'au 29/10/2026 ils étaient passés en `unknown[]`, et
// l'ajout d'un champ obligatoire au contrat les avait laissés muets — quatorze tests
// tombés d'un coup sans que `tsc` ne dise rien.

const ETAT = "GET /api/pairing/git-connections";

const CONFIEES: ConfidedGitState = {
  peer_base_url: "https://parametrage.example.org",
  revision: 7,
  received_at: "2026-10-30T07:00:00+00:00",
  connections: [
    {
      id: "yoops",
      label: "Forge yoops",
      base_url: "https://github.com/yoops",
      confided_at: "2026-10-30T06:00:00+00:00",
      renewed_at: null,
      workspaces: [{ id: "atelier", repo_url: "https://github.com/yoops/atelier" }],
    },
  ],
};

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
  it("shows each connection with the workspaces and repositories it serves", async () => {
    monte({ [ETAT]: { status: 200, body: CONFIEES } });

    expect(await screen.findByText("Forge yoops")).toBeInTheDocument();
    expect(screen.getByText("https://github.com/yoops")).toBeInTheDocument();
    expect(screen.getByText("atelier")).toBeInTheDocument();
    expect(screen.getByText("https://github.com/yoops/atelier")).toBeInTheDocument();
    expect(screen.getByText("revision 7")).toBeInTheDocument();
    // Jamais renouvelé est un ÉTAT, pas une donnée manquante : il se lit.
    expect(screen.getByText("Never renewed")).toBeInTheDocument();
  });

  it("says no configuration module is paired, rather than showing an empty list", async () => {
    // Critère 7 : « le dit plutôt que de laisser croire à une panne de la forge ». Une
    // liste vide se lirait comme une transmission perdue.
    monte({
      [ETAT]: {
        status: 200,
        body: { peer_base_url: null, revision: null, received_at: null, connections: [] },
      },
    });

    expect(await screen.findByText(/No configuration module is paired/i)).toBeInTheDocument();
    expect(screen.getByText(/not a forge failure/i)).toBeInTheDocument();
  });

  it("distinguishes a paired module that has confided nothing yet", async () => {
    monte({
      [ETAT]: {
        status: 200,
        body: {
          peer_base_url: "https://parametrage.example.org",
          revision: null,
          received_at: null,
          connections: [],
        },
      },
    });

    expect(await screen.findByText(/has not confided any connection yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/No configuration module is paired/i)).not.toBeInTheDocument();
  });

  it("names a credential that no longer opens as a credential problem", async () => {
    // C'est exactement ce que le critère 6 veut distinguer d'une panne de forge : le
    // geste à faire est de le faire reconfier, pas de chercher du côté du dépôt.
    monte({
      [ETAT]: { status: 200, body: CONFIEES },
      "GET /api/pairing/git-connections/yoops": {
        status: 200,
        body: { connection: CONFIEES.connections[0], credential_readable: false },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Test the credential" }));

    expect(await screen.findByText(/MILES_SECRETS_KEY changed/i)).toBeInTheDocument();
    expect(screen.getByText(/nothing to look for on the repository side/i)).toBeInTheDocument();
  });

  it("confirms a readable credential, which is the ordinary case", async () => {
    monte({
      [ETAT]: { status: 200, body: CONFIEES },
      "GET /api/pairing/git-connections/yoops": {
        status: 200,
        body: { connection: CONFIEES.connections[0], credential_readable: true },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Test the credential" }));

    expect(await screen.findByText(/usable as is/i)).toBeInTheDocument();
  });
});
