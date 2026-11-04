import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PairingScreen } from "@miles/socle-web";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { EnvironnementAssigne } from "./EnvironnementAssigne";

const ENROLEMENT = "https://enrolement.example.org";

const PAIR = {
  base_url: ENROLEMENT,
  declared_name: "Environnement de recette",
  contact_url: ENROLEMENT,
  revoked_at: null,
  public_key: "A".repeat(43),
  public_key_fingerprint: "82876eb0c19c35fdf589d74b1d96ca65",
  algorithm: "ed25519",
  created_at: "2026-10-20T08:00:00+00:00",
  updated_at: "2026-10-20T08:00:00+00:00",
};

const RECETTE = {
  slug: "recette",
  label: "Environnement de recette",
  fetched_at: "2026-10-29T09:00:00+00:00",
};

function etatRoute(body: unknown): Routes {
  return {
    "GET /api/identity/pairing/state": { status: 200, body },
    // L'écran interroge AUSSI cette route dès qu'un pair est affiché. Sans elle dans le
    // jeu d'essai, tous les tests du pair exerceraient en silence le chemin d'erreur de
    // ce bloc, et resteraient verts — la leçon du 29/10/2026 sur les champs absents, vue
    // à l'échelle d'une requête entière.
    "GET /api/identity/environment": { status: 200, body: { environment: RECETTE, fresh: true } },
  };
}

/** Le jeu d'essai de l'environnement assigné, à poser par-dessus l'état. */
function environnementRoute(body: unknown, status = 200): Routes {
  return { "GET /api/identity/environment": { status, body } };
}

function monte(routes: Routes) {
  const calls = mockApi(routes);
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {/* L'écran du socle COMPOSÉ comme `App.tsx` le compose : sans cela, le test
          éprouverait un assemblage que personne ne rend. */}
      <PairingScreen peerExtra={<EnvironnementAssigne />} />
    </QueryClientProvider>,
  );
  return calls;
}

describe("l'environnement que l'enrôlement assigne à ce module", () => {
  it("names the assigned environment by label and slug, read from the peer", async () => {
    // Critère 1 : c'est le seul nom qui fasse autorité — il est posé par un humain chez
    // l'enrôlement, alors que le nom déclaré est ce que cette stack dit d'elle-même.
    const appels = monte(etatRoute({ state: "apparie", attempt: null, peer: PAIR }));

    expect(await screen.findByText("Assigned environment")).toBeInTheDocument();
    expect(screen.getByText("recette")).toBeInTheDocument();
    // L'appel est réellement parti : une valeur affichée sans requête serait un cache.
    expect(appels.some((appel) => appel.key === "GET /api/identity/environment")).toBe(true);
  });

  it("dates the memorized value and says it could not be refreshed", async () => {
    // Critère 3 : un repli qui ne se dit pas est indiscernable d'un bug. La date est là
    // pour que l'administrateur sache de quand parle ce qu'il lit.
    monte({
      ...etatRoute({ state: "apparie", attempt: null, peer: PAIR }),
      ...environnementRoute({ environment: RECETTE, fresh: false }),
    });

    expect(await screen.findByText(/could not be reached to refresh it/i)).toBeInTheDocument();
    expect(screen.getByText("recette")).toBeInTheDocument();
  });

  it("does not show an empty value when nothing has ever been read", async () => {
    // Critère 4 : « injoignable et jamais rien su » ne se lit pas « aucun environnement
    // assigné ». Les deux rendent `environment: null`, et seul `fresh` les sépare.
    monte({
      ...etatRoute({ state: "apparie", attempt: null, peer: PAIR }),
      ...environnementRoute({ environment: null, fresh: false }),
    });

    expect(await screen.findByText(/could not be reached, and no environment/i)).toBeInTheDocument();
    expect(screen.queryByText(/has not linked us to any environment/i)).toBeNull();
  });

  it("says so when the peer answers that no environment is assigned", async () => {
    // Critère 5, l'autre moitié : une réponse FRAÎCHE qui dit « rien » se lit « rien »,
    // et non « on n'a pas pu savoir ».
    monte({
      ...etatRoute({ state: "apparie", attempt: null, peer: PAIR }),
      ...environnementRoute({ environment: null, fresh: true }),
    });

    expect(await screen.findByText(/has not linked us to any environment/i)).toBeInTheDocument();
    expect(screen.queryByText(/could not be reached, and no environment/i)).toBeNull();
  });

  it("asks for the assigned environment only once a pairing exists", async () => {
    // Il n'y a personne à qui demander sans pair, et la route répond 404 : l'appeler
    // quand même ferait afficher une erreur là où il n'y a rien d'anormal.
    const appels = monte(etatRoute({ state: "non_apparie", attempt: null, peer: null }));

    expect(await screen.findByText("Not paired")).toBeInTheDocument();
    expect(appels.some((appel) => appel.key === "GET /api/identity/environment")).toBe(false);
  });

  it("says what THIS module loses on a re-pairing, in its own words", async () => {
    // L'écran est au socle, qui ne peut dire que du neutre — « ce qui lui avait été
    // confié ». Ce que perd un environnement, lui, se compte en devices, et c'est le
    // produit qui le dit en redéfinissant `peering.repair.body`. Sans ce test, la
    // redéfinition pourrait sauter sans que rien ne rougisse : l'écran afficherait le
    // neutre du socle, qui n'est pas faux — seulement moins vrai.
    monte(etatRoute({ state: "apparie", attempt: null, peer: PAIR }));

    fireEvent.click(await screen.findByRole("button", { name: "Replace the pairing" }));

    expect(
      within(screen.getByRole("dialog")).getByText(/will no longer be assigned by it/i),
    ).toBeInTheDocument();
  });
});
