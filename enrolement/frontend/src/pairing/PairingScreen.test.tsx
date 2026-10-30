import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { PairedEnvironment, PairingRequest } from "../api/pairing";
import { PairingScreen } from "./PairingScreen";
import "../i18n/i18n";

const DANS_UNE_HEURE = new Date(Date.now() + 3_600_000).toISOString();

// L'environnement du référentiel, désigné : sans lui le code n'est pas révélable, et
// les cas qui ne portent PAS sur la désignation partiraient tous d'un état refusé.
const RECETTE = { id: "5e1b3a0c-0000-4000-8000-000000000001", slug: "recette", label: "Recette" };

// TYPÉS, et ce n'est pas de la décoration : jusqu'au 29/10/2026 ces jeux d'essai étaient
// passés en `unknown[]`, et l'ajout d'un champ obligatoire au contrat les a laissés muets
// — quatorze tests sont tombés d'un coup sans que `tsc` n'ait rien dit. Le type est ce qui
// fait rougir le jeu d'essai au bon endroit : à la compilation, pas dans un rendu.
const DEMANDE: PairingRequest = {
  base_url: "https://env-recette.example.org",
  name: "Environnement de recette",
  public_key_fingerprint: "4da291e81e6f8868f2b47bbed46d6925",
  algorithm: "ed25519",
  created_at: "2026-10-28T09:00:00+00:00",
  expires_at: DANS_UNE_HEURE,
  species: "environnement",
  environment: RECETTE,
};

// Le module de paramétrage : une AUTRE espèce de demandeur, et tout ce qui en découle se
// lit sur ce champ. Il ne reçoit pas de devices, donc aucune désignation ne l'attend — et
// son code est révélable sans elle.
const DEMANDE_PARAMETRAGE: PairingRequest = {
  ...DEMANDE,
  base_url: "https://parametrage.example.org",
  name: "Portail de configuration",
  species: "parametrage",
  environment: null,
};

const APPARIE_BASE_URL = "https://env-production.example.org";

const APPARIE: PairedEnvironment = {
  base_url: APPARIE_BASE_URL,
  name: "Environnement de production",
  public_key: "A".repeat(43),
  public_key_fingerprint: "82876eb0c19c35fdf589d74b1d96ca65",
  algorithm: "ed25519",
  created_at: "2026-10-20T08:00:00+00:00",
  updated_at: "2026-10-20T08:00:00+00:00",
  device_count: null,
  // Le cas ordinaire : on joint la stack là où elle se nomme. Sans ce champ, la branche
  // qui le lit resterait invisible aux tests — leçon du 29/10/2026.
  contact_url: APPARIE_BASE_URL,
  species: "environnement",
  environment: {
    id: "5e1b3a0c-0000-4000-8000-000000000002",
    slug: "production",
    label: "Production",
  },
};

const APPARIE_PARAMETRAGE: PairedEnvironment = {
  ...APPARIE,
  base_url: "https://parametrage.example.org",
  name: "Portail de configuration",
  species: "parametrage",
  // Jamais rattaché, et la base le refuse : ce n'est pas « à rattacher », c'est sans objet.
  environment: null,
};

const ENVIRONNEMENTS = [
  { ...RECETTE, created_at: "2026-10-27T08:00:00+00:00", updated_at: "2026-10-27T08:00:00+00:00",
    paired_base_url: null, designated_base_url: null },
  { id: "5e1b3a0c-0000-4000-8000-000000000003", slug: "production", label: "Production",
    created_at: "2026-10-20T08:00:00+00:00", updated_at: "2026-10-20T08:00:00+00:00",
    paired_base_url: APPARIE_BASE_URL, designated_base_url: null },
];

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

function routes(
  demandes: PairingRequest[],
  apparies: PairedEnvironment[],
  autres: Routes = {},
): Routes {
  return {
    "GET /api/pairing/requests": { status: 200, body: demandes },
    "GET /api/pairing/peers": { status: 200, body: apparies },
    "GET /api/environments": { status: 200, body: ENVIRONNEMENTS },
    // L'écran porte désormais la carte des connexions git confiées : sans cette route,
    // elle rend une alerte, et les cas qui vérifient « aucune alerte » rougissent pour
    // une raison qui n'a rien à voir avec eux. Son défaut est l'état le plus neutre —
    // un module de paramétrage apparié qui n'a encore rien confié.
    "GET /api/pairing/git-connections": {
      status: 200,
      body: {
        peer_base_url: "https://parametrage.example.org",
        revision: null,
        received_at: null,
        connections: [],
      },
    },
    ...autres,
  };
}

describe("écran d'appariement du module d'enrôlement", () => {
  it("says there is nothing pending without suggesting a problem", async () => {
    monte(routes([], []));

    // Un état vide NEUTRE : aucune demande en attente est le cas ordinaire, pas une panne.
    expect(await screen.findByText("No pending request.")).toBeInTheDocument();
    // Chaque espèce a son bloc, et chacun dit le sien : « aucun environnement » ne
    // renseigne pas sur le module de paramétrage, qui est une autre question.
    expect(screen.getByText("No environment paired.")).toBeInTheDocument();
    expect(screen.getByText("No configuration module paired.")).toBeInTheDocument();
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

  it("shows the contact address only when it is not where the stack names itself", async () => {
    monte(routes([], [APPARIE]));
    expect(await screen.findByText("Environnement de production")).toBeInTheDocument();
    expect(screen.queryByText("Reached at")).toBeNull();
  });

  it("saves a new contact address without touching the stack's identity", async () => {
    const CONTACT = "http://100.74.9.236:8082";
    const appels = monte(
      routes([], [{ ...APPARIE, contact_url: CONTACT }], {
        [`PUT /api/pairing/peers/contact?base_url=${encodeURIComponent(APPARIE_BASE_URL)}`]: {
          status: 200,
          body: { ...APPARIE, contact_url: CONTACT },
        },
      }),
    );

    // Différente de l'identité : elle est montrée, et dite pour ce qu'elle est.
    expect(await screen.findByText(CONTACT)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Change contact address" }));
    fireEvent.change(screen.getByLabelText("Contact address"), {
      target: { value: "http://10.0.0.9:8082" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save address" }));

    await waitFor(() =>
      expect(
        appels.find((appel) => appel.key.startsWith("PUT /api/pairing/peers/contact"))?.body,
      ).toEqual({ contact_url: "http://10.0.0.9:8082" }),
    );
  });

  it("names the environment and the device consequence before revoking", async () => {
    // Critère 1 : l'humain doit voir la conséquence AVANT de la provoquer. Le nom de
    // l'environnement et le sort des devices sont les deux seules choses qui rendent ce
    // geste décidable.
    monte(routes([], [APPARIE]));

    fireEvent.click(await screen.findByRole("button", { name: "Revoke pairing" }));

    const dialogue = within(screen.getByRole("dialog"));
    expect(dialogue.getByText(/Production/)).toBeInTheDocument();
    expect(dialogue.getByText(/production/)).toBeInTheDocument();
    // Le nombre de devices est INCONNU, et le dire est la seule réponse honnête : « 0
    // devices seront remis en attente » serait une affirmation fausse sur le parc, et
    // c'est sur cette phrase que l'humain déciderait.
    expect(dialogue.getByText(/device registry does not exist yet/i)).toBeInTheDocument();
    expect(dialogue.getByText(/key will be destroyed/i)).toBeInTheDocument();
    expect(dialogue.getByText(/stays in the registry/i)).toBeInTheDocument();
  });

  it("asks for a confirmation before revoking, then deletes the pairing", async () => {
    const appels = monte(
      routes([], [APPARIE], {
        [`DELETE /api/pairing/peers?base_url=${encodeURIComponent(APPARIE_BASE_URL)}`]: {
          status: 204,
        },
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Revoke pairing" }));
    const dialogue = within(screen.getByRole("dialog"));
    // La garde doit mordre : tant qu'on n'a pas confirmé, aucune clé n'est détruite.
    expect(appels.some((appel) => appel.key.startsWith("DELETE"))).toBe(false);

    fireEvent.click(dialogue.getByRole("button", { name: "Revoke" }));

    await waitFor(() =>
      expect(appels.some((appel) => appel.key.startsWith("DELETE /api/pairing/peers"))).toBe(true),
    );
  });

  it("offers revocation on an inherited pairing that carries no environment", async () => {
    // Un appariement hérité est le cas où l'on a LE PLUS besoin de révoquer : il date
    // d'avant la désignation, et rien d'autre ne permet de s'en défaire.
    monte(routes([], [{ ...APPARIE, environment: null }]));

    fireEvent.click(await screen.findByRole("button", { name: "Revoke pairing" }));

    const dialogue = within(screen.getByRole("dialog"));
    expect(dialogue.getByText(/not attached to any environment/i)).toBeInTheDocument();
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
  it("refuses to reveal the code before an environment is chosen, and says why", async () => {
    // Critère 1 : un bouton grisé MUET fait chercher la panne du côté des clés ou du
    // réseau. La raison doit être écrite, pas seulement signifiée par un bouton éteint.
    const appels = monte(routes([{ ...DEMANDE, environment: null }], []));

    expect(await screen.findByRole("button", { name: "Show code" })).toBeDisabled();
    expect(
      screen.getByText(/showing it accepts the pairing, and we must know what to link it to/i),
    ).toBeInTheDocument();
    expect(appels.some((appel) => appel.key.startsWith("GET /api/pairing/code"))).toBe(false);
  });

  it("sends the chosen environment, then lets the code be revealed", async () => {
    const appels = monte(
      routes([{ ...DEMANDE, environment: null }], [], {
        [`PUT /api/pairing/requests/environment?base_url=${encodeURIComponent(DEMANDE.base_url)}`]:
          { status: 200, body: DEMANDE },
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Choose the environment" }));
    const liste = await screen.findByLabelText("Environment from the registry");
    // L'option est ATTENDUE : le référentiel se charge au montage du composant, et
    // choisir une valeur qui n'est pas encore là ne change rien au champ.
    await within(liste).findByRole("option", { name: /Recette/ });
    fireEvent.change(liste, { target: { value: RECETTE.id } });
    fireEvent.click(screen.getByRole("button", { name: "Choose" }));

    await waitFor(() =>
      expect(
        appels.find((appel) => appel.key.startsWith("PUT /api/pairing/requests/environment"))?.body,
      ).toEqual({ environment_id: RECETTE.id }),
    );
  });

  it("never offers an environment that already carries a pairing", async () => {
    // Deux stacks appariées pour un même environnement, et « à quelle stack appartient
    // ce device » n'a plus de réponse unique.
    monte(routes([{ ...DEMANDE, environment: null }], [APPARIE]));

    fireEvent.click(await screen.findByRole("button", { name: "Choose the environment" }));
    const liste = await screen.findByLabelText("Environment from the registry");

    // Attendu, et non lu tout de suite : la liste du référentiel est chargée par le
    // composant au montage, donc APRÈS que le champ existe.
    expect(await within(liste).findByRole("option", { name: /Recette/ })).toBeInTheDocument();
    expect(within(liste).queryByRole("option", { name: /Production/ })).toBeNull();
  });

  it("creates an environment from the pairing screen and links the request at once", async () => {
    // Critère 3 : un environnement créé puis laissé non désigné ferait croire le geste
    // terminé alors que le code n'est toujours pas révélable.
    const neuf = { ...RECETTE, id: "5e1b3a0c-0000-4000-8000-000000000009", slug: "preprod" };
    const appels = monte(
      routes([{ ...DEMANDE, environment: null }], [], {
        "POST /api/environments": { status: 201, body: neuf },
        [`PUT /api/pairing/requests/environment?base_url=${encodeURIComponent(DEMANDE.base_url)}`]:
          { status: 200, body: DEMANDE },
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Choose the environment" }));
    fireEvent.click(screen.getByRole("button", { name: "Declare an environment" }));
    // Le slug se DÉRIVE du libellé, comme au référentiel : c'est le même formulaire,
    // et le réécrire ici ferait diverger les deux au premier changement de règle.
    fireEvent.change(await screen.findByLabelText("Label"), { target: { value: "Pré-prod" } });
    expect(screen.getByLabelText("Slug")).toHaveValue("pre-prod");
    fireEvent.click(screen.getByRole("button", { name: "Declare and choose" }));

    await waitFor(() =>
      expect(
        appels.find((appel) => appel.key.startsWith("PUT /api/pairing/requests/environment"))?.body,
      ).toEqual({ environment_id: neuf.id }),
    );
  });

  it("flags an inherited pairing as needing a link, and links it without touching the keys", async () => {
    // Critère 8 : un appariement conclu avant que la désignation n'existe. L'état est
    // transitoire HÉRITÉ, pas l'état normal — d'où la pastille d'alerte.
    const herite = { ...APPARIE, environment: null };
    const appels = monte(
      routes([], [herite], {
        [`PUT /api/pairing/peers/environment?base_url=${encodeURIComponent(APPARIE_BASE_URL)}`]: {
          status: 200,
          body: APPARIE,
        },
      }),
    );

    expect(await screen.findByText("To be linked")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Link to an environment" }));
    const liste = await screen.findByLabelText("Environment from the registry");
    await within(liste).findByRole("option", { name: /Recette/ });
    fireEvent.change(liste, { target: { value: RECETTE.id } });
    fireEvent.click(screen.getByRole("button", { name: "Link" }));

    await waitFor(() =>
      expect(
        appels.find((appel) => appel.key.startsWith("PUT /api/pairing/peers/environment"))?.body,
      ).toEqual({ environment_id: RECETTE.id }),
    );
  });

  it("never offers to LINK a pairing that already carries an environment", async () => {
    // Deux gestes distincts, et le rattachement est celui d'un appariement HÉRITÉ : le
    // proposer sur un appariement déjà rattaché ferait écrire « rattaché » au journal là
    // où il s'est produit un déplacement.
    monte(routes([], [APPARIE]));

    expect(await screen.findByText("Production")).toBeInTheDocument();
    // Le motif nomme le geste refusé et lui seul : il a débordé une fois, le 29/10/2026,
    // en attrapant « Change contact address » — qui ne déplace rien.
    expect(screen.queryByRole("button", { name: /link to an environment/i })).toBeNull();
    expect(screen.getByRole("button", { name: /change the environment/i })).toBeInTheDocument();
  });

  it("names both environments, by label and slug, before moving the pairing", async () => {
    // Critère 1 : la confirmation nomme l'environnement quitté ET celui qui est pris, par
    // leur libellé et leur slug. C'est le slug qui s'écrit dans une procédure, et deux
    // libellés se ressemblent.
    const appels = monte(
      routes([], [APPARIE], {
        [`PUT /api/pairing/peers/environment?base_url=${encodeURIComponent(APPARIE_BASE_URL)}`]: {
          status: 200,
          body: { ...APPARIE, environment: RECETTE },
        },
      }),
    );

    expect(await screen.findByText("Production")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change the environment" }));
    const liste = await screen.findByLabelText("Environment from the registry");
    await within(liste).findByRole("option", { name: /Recette/ });
    fireEvent.change(liste, { target: { value: RECETTE.id } });
    fireEvent.click(screen.getByRole("button", { name: "Pick this environment" }));

    const dialogue = within(screen.getByRole("dialog"));
    expect(dialogue.getByText(/“Production” \(production\)/)).toBeInTheDocument();
    expect(dialogue.getByText(/“Recette” \(recette\)/)).toBeInTheDocument();
    // Tant qu'on n'a pas confirmé, RIEN n'est envoyé : le choix dans la liste déroulante
    // n'est pas le geste.
    expect(appels.some((appel) => appel.key.startsWith("PUT /api/pairing/peers/environment"))).toBe(
      false,
    );

    fireEvent.click(dialogue.getByRole("button", { name: "Change the environment" }));

    await waitFor(() =>
      expect(
        appels.find((appel) => appel.key.startsWith("PUT /api/pairing/peers/environment"))?.body,
      ).toEqual({ environment_id: RECETTE.id }),
    );
  });

  it("names the devices as the reason when the move is refused", async () => {
    // Le refus RENVOIE vers le déplacement des devices : un message générique enverrait
    // chercher du côté des droits ou du réseau.
    monte(
      routes([], [APPARIE], {
        [`PUT /api/pairing/peers/environment?base_url=${encodeURIComponent(APPARIE_BASE_URL)}`]: {
          status: 409,
          body: { detail: "appariement_porte_des_devices" },
        },
      }),
    );

    expect(await screen.findByText("Production")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change the environment" }));
    const liste = await screen.findByLabelText("Environment from the registry");
    await within(liste).findByRole("option", { name: /Recette/ });
    fireEvent.change(liste, { target: { value: RECETTE.id } });
    fireEvent.click(screen.getByRole("button", { name: "Pick this environment" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Change the environment" }),
    );

    expect(await screen.findByText(/Move the devices to the target environment first/i)).toBeInTheDocument();
  });

  it("tells to refresh when the environment was changed in another tab", async () => {
    // Une COURSE, pas une règle. Confondue avec « cet appariement est conclu », elle
    // ferait croire le geste interdit alors qu'il est seulement arrivé second.
    monte(
      routes([], [APPARIE], {
        [`PUT /api/pairing/peers/environment?base_url=${encodeURIComponent(APPARIE_BASE_URL)}`]: {
          status: 409,
          body: { detail: "appariement_change_ailleurs" },
        },
      }),
    );

    expect(await screen.findByText("Production")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change the environment" }));
    const liste = await screen.findByLabelText("Environment from the registry");
    await within(liste).findByRole("option", { name: /Recette/ });
    fireEvent.change(liste, { target: { value: RECETTE.id } });
    fireEvent.click(screen.getByRole("button", { name: "Pick this environment" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Change the environment" }),
    );

    expect(await screen.findByText(/Refresh the list before trying again/i)).toBeInTheDocument();
  });

  it("names the refusal when the chosen environment was taken in the meantime", async () => {
    const appels = monte(
      routes([{ ...DEMANDE, environment: null }], [], {
        [`PUT /api/pairing/requests/environment?base_url=${encodeURIComponent(DEMANDE.base_url)}`]:
          { status: 409, body: { detail: "environnement_apparie" } },
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Choose the environment" }));
    const liste = await screen.findByLabelText("Environment from the registry");
    await within(liste).findByRole("option", { name: /Recette/ });
    fireEvent.change(liste, { target: { value: RECETTE.id } });
    fireEvent.click(screen.getByRole("button", { name: "Choose" }));

    expect(
      await screen.findByText(/Another pairing already carries this environment/i),
    ).toBeInTheDocument();
    expect(appels.some((appel) => appel.key.startsWith("PUT"))).toBe(true);
  });

  it("shows the registry label and slug of a paired environment", async () => {
    // Critère 6 : le nom DÉCLARÉ reste affiché, et ne tient lieu de nom nulle part.
    monte(routes([], [APPARIE]));

    expect(await screen.findByText("Production")).toBeInTheDocument();
    expect(screen.getByText("production")).toBeInTheDocument();
    expect(screen.getByText("Environnement de production")).toBeInTheDocument();
  });

  it("names the kind of a pending requester, and what accepting it entails", async () => {
    // Critère 2 : l'espèce est visible sur l'écran des demandes. Le libellé SEUL ne
    // suffirait pas — « module de paramétrage » ne dit pas à un humain qu'il s'apprête à
    // lui confier des connexions git, et c'est sur cela que la décision se prend.
    monte(routes([DEMANDE, DEMANDE_PARAMETRAGE], []));

    await screen.findByText("Portail de configuration");
    const demandes = screen
      .getByRole("heading", { name: "Pending requests" })
      .closest(".card") as HTMLElement;
    expect(within(demandes).getByText("Configuration module")).toBeInTheDocument();
    expect(
      within(demandes).getByText(/entrusted with the git connections/i),
    ).toBeInTheDocument();
    expect(
      within(demandes).getByText("Receives devices from this module."),
    ).toBeInTheDocument();
  });

  it("names the kind in the paired list too, by its own block", async () => {
    // Même critère, et l'autre moitié : une liste qui ne dirait l'espèce qu'à l'acceptation
    // laisserait, un mois plus tard, « pourquoi cette stack a-t-elle ces secrets ? » sans
    // réponse lisible à l'écran. Depuis la séparation par espèce (Gael, 30/10/2026), c'est
    // le TITRE du bloc qui la porte, et sa conséquence une seule fois dessous.
    monte(routes([], [APPARIE_PARAMETRAGE]));

    await screen.findByText("Portail de configuration");
    const bloc = screen
      .getByRole("heading", { name: "Paired configuration module" })
      .closest(".card") as HTMLElement;
    expect(within(bloc).getByText(/entrusted with the git connections/i)).toBeInTheDocument();
    expect(within(bloc).getByText("Portail de configuration")).toBeInTheDocument();
    // Et il n'est PAS dans le bloc des environnements, qui se dit vide.
    expect(screen.getByText("No environment paired.")).toBeInTheDocument();
  });

  it("puts the configuration module above the environments", async () => {
    // L'ordre demandé (Gael, 30/10/2026) : ce qu'on confie se lit avant le parc, et c'est
    // aussi l'ordre dont les connexions confiées découlent.
    monte(routes([], [APPARIE_PARAMETRAGE, APPARIE]));

    await screen.findByText("Portail de configuration");
    const titres = [...document.querySelectorAll(".card-head h2")].map((e) => e.textContent);
    expect(titres).toEqual([
      "Pending requests",
      "Paired configuration module",
      "Confided git connections",
      "Paired environments",
    ]);
  });

  it("never asks to assign an environment to a configuration module", async () => {
    // Il ne reçoit pas de devices : lui réclamer un rattachement serait réclamer un geste
    // qui n'existe pas, et le serveur refuse le choix que l'écran aurait proposé. L'écran
    // suit donc l'ESPÈCE, et jamais l'absence de valeur.
    monte(routes([DEMANDE_PARAMETRAGE], [APPARIE_PARAMETRAGE]));

    // Les deux listes la portent — la demande en attente et l'appariement conclu —, et les
    // deux doivent se taire sur le rattachement.
    expect(await screen.findAllByText("Portail de configuration")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Choose the environment" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Link to an environment" })).toBeNull();
    expect(screen.queryByText("To be attached")).toBeNull();
  });

  it("reveals the code of a configuration module without any designation", async () => {
    // La désignation conditionne la révélation pour un ENVIRONNEMENT, et pour lui seul :
    // exiger la même chose du module de paramétrage rendrait son appariement impossible.
    monte(
      routes([DEMANDE_PARAMETRAGE], [], {
        [`GET /api/pairing/code?base_url=${encodeURIComponent(DEMANDE_PARAMETRAGE.base_url)}`]: {
          status: 200,
          body: { base_url: DEMANDE_PARAMETRAGE.base_url, code: "314159", seconds_remaining: 20 },
        },
      }),
    );

    const bouton = await screen.findByRole("button", { name: "Show code" });
    expect(bouton).toBeEnabled();
    fireEvent.click(bouton);

    expect(await screen.findByText("314159")).toBeInTheDocument();
  });

  it("tells a revoked configuration module what it loses, not how many devices", async () => {
    // Les devices ne le concernent pas. Afficher « le nombre n'est pas connu » à son
    // sujet ferait croire qu'il en porte peut-être, et c'est faux par construction.
    monte(routes([], [APPARIE_PARAMETRAGE]));

    fireEvent.click(await screen.findByRole("button", { name: "Revoke pairing" }));

    expect(
      await screen.findByText(/pairing of configuration module/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/ceases to be/i)).toBeInTheDocument();
    expect(screen.queryByText(/device registry does not exist yet/i)).toBeNull();
  });
});
