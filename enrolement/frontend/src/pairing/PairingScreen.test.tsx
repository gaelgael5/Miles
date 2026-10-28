import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { PairingScreen } from "./PairingScreen";
import "../i18n/i18n";

const DANS_UNE_HEURE = new Date(Date.now() + 3_600_000).toISOString();

const DEMANDE = {
  base_url: "https://env-recette.example.org",
  name: "Environnement de recette",
  public_key_fingerprint: "4da291e81e6f8868f2b47bbed46d6925",
  algorithm: "ed25519",
  created_at: "2026-10-28T09:00:00+00:00",
  expires_at: DANS_UNE_HEURE,
};

const APPARIE = {
  base_url: "https://env-production.example.org",
  name: "Environnement de production",
  public_key: "A".repeat(43),
  public_key_fingerprint: "82876eb0c19c35fdf589d74b1d96ca65",
  algorithm: "ed25519",
  created_at: "2026-10-20T08:00:00+00:00",
  updated_at: "2026-10-20T08:00:00+00:00",
  device_count: null,
};

function monte(routes: Routes) {
  const calls = mockApi(routes);
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <PairingScreen />
    </QueryClientProvider>,
  );
  return calls;
}

function routes(demandes: unknown[], apparies: unknown[], autres: Routes = {}): Routes {
  return {
    "GET /api/pairing/requests": { status: 200, body: demandes },
    "GET /api/pairing/peers": { status: 200, body: apparies },
    ...autres,
  };
}

describe("écran d'appariement du module d'enrôlement", () => {
  it("says there is nothing pending without suggesting a problem", async () => {
    monte(routes([], []));

    // Un état vide NEUTRE : aucune demande en attente est le cas ordinaire, pas une panne.
    expect(await screen.findByText("No pending request.")).toBeInTheDocument();
    expect(screen.getByText("No paired environment.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the declared name, the URL and the key fingerprint of a request", async () => {
    monte(routes([DEMANDE], []));

    expect(await screen.findByText("Environnement de recette")).toBeInTheDocument();
    expect(screen.getByText(DEMANDE.base_url)).toBeInTheDocument();
    expect(screen.getByText(DEMANDE.public_key_fingerprint)).toBeInTheDocument();
  });

  it("renders a hostile declared name as text and never as markup", async () => {
    // Le nom vient d'un tiers que personne n'a authentifié. Le test regarde le DOM, pas
    // le texte : une balise interprétée produirait un ÉLÉMENT, et aucun texte visible.
    const hostile = '<img src=x onerror="document.title=\'pwned\'">';
    monte(routes([{ ...DEMANDE, name: hostile }], []));

    expect(await screen.findByText(hostile)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(document.title).not.toBe("pwned");
  });

  it("falls back to a label when no name was declared", async () => {
    monte(routes([{ ...DEMANDE, name: null }], []));

    expect(await screen.findByText("No declared name")).toBeInTheDocument();
  });

  it("keeps two requests with the same name distinguishable by their URL", async () => {
    // Le nom déclaré n'identifie RIEN : deux environnements peuvent porter le même.
    const second = { ...DEMANDE, base_url: "https://env-autre.example.org" };
    monte(routes([DEMANDE, second], []));

    expect(await screen.findAllByText("Environnement de recette")).toHaveLength(2);
    expect(screen.getByText(DEMANDE.base_url)).toBeInTheDocument();
    expect(screen.getByText(second.base_url)).toBeInTheDocument();
  });

  it("reveals the code only on demand, and offers no way out but the clipboard", async () => {
    const appels = monte(
      routes([DEMANDE], [], {
        [`GET /api/pairing/code?base_url=${encodeURIComponent(DEMANDE.base_url)}`]: {
          status: 200,
          body: { base_url: DEMANDE.base_url, code: "314159", seconds_remaining: 21 },
        },
      }),
    );

    // Rien n'est demandé tant que personne n'a cliqué : le code est périssable, et
    // l'afficher d'office le ferait traîner sur un écran que personne ne regarde.
    expect(await screen.findByText("Environnement de recette")).toBeInTheDocument();
    expect(appels.some((appel) => appel.key.startsWith("GET /api/pairing/code"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Show code" }));

    expect(await screen.findByText("314159")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy code" })).toBeInTheDocument();
    // Ni impression, ni téléchargement, ni export : la seule sortie est le presse-papiers.
    expect(screen.queryByRole("button", { name: /print|download|export/i })).toBeNull();
    expect(document.querySelector("a[download]")).toBeNull();
  });

  it("tells the administrator that handing over the code is what accepts", async () => {
    monte(routes([DEMANDE], []));

    expect(
      await screen.findByText(/that gesture, and only it, is the acceptance/i),
    ).toBeInTheDocument();
  });

  it("asks for a confirmation before rejecting, then deletes the request", async () => {
    const appels = monte(
      routes([DEMANDE], [], {
        [`DELETE /api/pairing/requests?base_url=${encodeURIComponent(DEMANDE.base_url)}`]: {
          status: 204,
        },
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const dialogue = within(screen.getByRole("dialog"));
    // La garde doit mordre : tant qu'on n'a pas confirmé, rien n'est envoyé.
    expect(appels.some((appel) => appel.key.startsWith("DELETE"))).toBe(false);

    fireEvent.click(dialogue.getByRole("button", { name: "Reject" }));

    await waitFor(() =>
      expect(appels.some((appel) => appel.key.startsWith("DELETE /api/pairing/requests"))).toBe(
        true,
      ),
    );
  });

  it("shows a dash rather than zero while the device registry does not exist", async () => {
    // Zéro se lirait « aucun device » sur un écran qui ne sait pas compter, et personne
    // ne distinguerait plus « vide » d'« ignoré ».
    monte(routes([], [APPARIE]));

    expect(await screen.findByText("Environnement de production")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("interpolates the countdowns instead of printing the template", async () => {
    // Trouvé dans un VRAI navigateur le 28/10/2026, pas sous jsdom : l'écran affichait
    // « in {{n}} min » parce que la clef était appelée avec `count` quand le gabarit
    // attend `n` — et `count` déclenche en plus la machinerie de pluriel d'i18next.
    // Aucun test n'ASSERTAIT le texte du compte à rebours : il ne pouvait rien prouver.
    monte(
      routes([{ ...DEMANDE, expires_at: new Date(Date.now() + 300_000).toISOString() }], [], {
        [`GET /api/pairing/code?base_url=${encodeURIComponent(DEMANDE.base_url)}`]: {
          status: 200,
          body: { base_url: DEMANDE.base_url, code: "314159", seconds_remaining: 21 },
        },
      }),
    );

    expect(await screen.findByText("in 5 min")).toBeInTheDocument();
    expect(screen.queryByText(/\{\{/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Show code" }));

    expect(await screen.findByText("renews in 21 s")).toBeInTheDocument();
    expect(screen.queryByText(/\{\{/)).toBeNull();
  });

  it("switches to hours when the deadline is far, rather than printing huge minutes", async () => {
    // La durée de vie d'une demande est PARAMÉTRABLE, jusqu'à sept jours : « in 10080 min »
    // serait exact et illisible. Vu dans un vrai navigateur avant d'être corrigé.
    monte(
      routes(
        [{ ...DEMANDE, expires_at: new Date(Date.now() + 3 * 3_600_000).toISOString() }],
        [],
      ),
    );

    expect(await screen.findByText("in 3 h")).toBeInTheDocument();
  });

  it("says plainly when a revealed request has vanished", async () => {
    const appels = monte(
      routes([DEMANDE], [], {
        [`GET /api/pairing/code?base_url=${encodeURIComponent(DEMANDE.base_url)}`]: {
          status: 404,
          body: { detail: "absent" },
        },
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Show code" }));

    expect(
      await screen.findByText(/no longer exists: it expired or was just rejected/i),
    ).toBeInTheDocument();
    expect(appels.some((appel) => appel.key.startsWith("GET /api/pairing/code"))).toBe(true);
  });
});
