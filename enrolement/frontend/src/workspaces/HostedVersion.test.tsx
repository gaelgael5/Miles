import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { HostedVersion } from "./HostedVersion";
import "../i18n/i18n";

const VERSIONS = "GET /api/environments/env-1/versions";
const ORDONNEE = "GET /api/environments/env-1/version";
const ORDONNER = "PUT /api/environments/env-1/version";
const RENVOYER = "POST /api/environments/env-1/version/resend";

const PUBLIEES = [
  {
    number: 2,
    label: "Réseau ferroviaire",
    commit: "b".repeat(40),
    author: "Alice <alice@annuaire.invalid>",
    saved_at: "2026-11-01T09:00:00Z",
    branch: "back/reseau/atelier",
  },
  {
    number: 1,
    label: "Première mise en service",
    commit: "a".repeat(40),
    author: "Alice <alice@annuaire.invalid>",
    saved_at: "2026-10-31T09:00:00Z",
    branch: null,
  },
];

const SERVIE = {
  number: 2,
  commit: "b".repeat(40),
  ordered_at: "2026-11-01T10:00:00Z",
  served_commit: "b".repeat(40),
  refusal: null,
  acked_at: "2026-11-01T10:00:05Z",
  up_to_date: true,
};

function monte(routes: Routes) {
  const calls = mockApi(routes);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HostedVersion environmentId="env-1" />
    </QueryClientProvider>,
  );
  return calls;
}

describe("version hébergée par un environnement", () => {
  it("lists the published versions with their label, author and branch", async () => {
    monte({
      [VERSIONS]: { status: 200, body: PUBLIEES },
      [ORDONNEE]: { status: 404, body: { detail: "aucune_version_ordonnee" } },
    });

    expect(await screen.findByText(/Réseau ferroviaire/)).toBeTruthy();
    expect(screen.getByText(/back\/reseau\/atelier/)).toBeTruthy();
    // La plus récente d'abord : c'est l'ordre que le serveur rend, et l'écran ne le refait pas.
    const titres = screen.getAllByText(/^Version \d/).map((n) => n.textContent ?? "");
    expect(titres.at(0)).toContain("Version 2");
  });

  it("says that no version is ordered rather than showing an empty line", async () => {
    monte({
      [VERSIONS]: { status: 200, body: PUBLIEES },
      [ORDONNEE]: { status: 404, body: { detail: "aucune_version_ordonnee" } },
    });

    // 404 est un ÉTAT ici, pas une panne : l'écran le dit, et propose de choisir.
    expect(await screen.findByText(/No version is ordered/)).toBeTruthy();
  });

  it("orders the version that was picked, by its number and never by its commit", async () => {
    const calls = monte({
      [VERSIONS]: { status: 200, body: PUBLIEES },
      [ORDONNEE]: { status: 404, body: { detail: "aucune_version_ordonnee" } },
      [ORDONNER]: { status: 200, body: SERVIE },
    });

    const boutons = await screen.findAllByRole("button", { name: "Associate" });
    fireEvent.click(boutons[0] as HTMLElement);

    await waitFor(() => expect(calls.find((c) => c.key === ORDONNER)).toBeDefined());
    // Le NUMÉRO seul : le commit est lu dans le dépôt par le serveur, et l'accepter
    // d'ici reviendrait à laisser désigner un contenu arbitraire du dépôt.
    expect(calls.find((c) => c.key === ORDONNER)?.body).toEqual({ number: 2 });
    expect(await screen.findByText("served")).toBeTruthy();
  });

  it("names what the stack refused, and offers to resend the order", async () => {
    const calls = monte({
      [VERSIONS]: { status: 200, body: PUBLIEES },
      [ORDONNEE]: {
        status: 200,
        body: { ...SERVIE, served_commit: null, refusal: "pair_injoignable", up_to_date: false },
      },
      [RENVOYER]: { status: 200, body: SERVIE },
    });

    expect(await screen.findByText("the stack did not answer")).toBeTruthy();
    // La date accompagne le refus : c'est un INSTANTANÉ, et « actuellement » serait faux.
    expect(screen.getByText(/as of /)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Resend the order" }));

    await waitFor(() => expect(calls.find((c) => c.key === RENVOYER)).toBeDefined());
    expect(await screen.findByText("served")).toBeTruthy();
  });

  it("names an unknown refusal code instead of hiding it", async () => {
    monte({
      [VERSIONS]: { status: 200, body: PUBLIEES },
      [ORDONNEE]: {
        status: 200,
        body: { ...SERVIE, served_commit: null, refusal: "venu_d_ailleurs", up_to_date: false },
      },
    });

    // Un code qu'on ne sait pas traduire se LIT quand même : masquer ce qu'on ne
    // comprend pas est ce qui rend un diagnostic impossible.
    expect(await screen.findByText(/venu_d_ailleurs/)).toBeTruthy();
  });

  it("tells that no workspace is placed rather than showing an empty list", async () => {
    monte({
      [VERSIONS]: { status: 409, body: { detail: "aucun_workspace_place" } },
      [ORDONNEE]: { status: 404, body: { detail: "aucune_version_ordonnee" } },
    });

    expect(await screen.findByText(/No workspace is placed/)).toBeTruthy();
  });

  it("carries what git said when the repository could not be read", async () => {
    monte({
      [VERSIONS]: {
        status: 422,
        body: { detail: { code: "depot_illisible", reason: "identifiants" } },
      },
      [ORDONNEE]: { status: 404, body: { detail: "aucune_version_ordonnee" } },
    });

    // « identifiants », « dépôt inexistant » et « injoignable » appellent trois gestes
    // différents : un message unique les enverrait chercher au même endroit.
    expect(await screen.findByText(/repository could not be read/)).toBeTruthy();
    expect(screen.getByText(/confided credential was refused by the forge/)).toBeTruthy();
  });

  it("says that the repository holds no version at all", async () => {
    monte({
      [VERSIONS]: { status: 200, body: [] },
      [ORDONNEE]: { status: 404, body: { detail: "aucune_version_ordonnee" } },
    });

    // Lu du dépôt, donc une liste vide est une vérité — contrairement à avant, où elle
    // n'aurait été que l'absence de route.
    expect(await screen.findByText(/no version saved in its repository/)).toBeTruthy();
  });

  it("marks the ordered version in the list instead of offering it again", async () => {
    monte({
      [VERSIONS]: { status: 200, body: PUBLIEES },
      [ORDONNEE]: { status: 200, body: SERVIE },
    });

    await screen.findByText(/Réseau ferroviaire/);
    // Une seule version est ordonnée : l'autre reste associable, celle-ci non.
    expect(screen.getAllByRole("button", { name: "Associate" })).toHaveLength(1);
    expect(screen.getByText("ordered")).toBeTruthy();
  });
});
