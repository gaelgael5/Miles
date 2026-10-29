import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { PairingScreen } from "./PairingScreen";
import "../i18n/i18n";

const DANS_UNE_HEURE = new Date(Date.now() + 3_600_000).toISOString();

// L'environnement du référentiel, désigné : sans lui le code n'est pas révélable, et
// les cas qui ne portent PAS sur la désignation partiraient tous d'un état refusé.
const RECETTE = { id: "5e1b3a0c-0000-4000-8000-000000000001", slug: "recette", label: "Recette" };

const DEMANDE = {
  base_url: "https://env-recette.example.org",
  name: "Environnement de recette",
  public_key_fingerprint: "4da291e81e6f8868f2b47bbed46d6925",
  algorithm: "ed25519",
  created_at: "2026-10-28T09:00:00+00:00",
  expires_at: DANS_UNE_HEURE,
  environment: RECETTE,
};

const APPARIE_BASE_URL = "https://env-production.example.org";

const APPARIE = {
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
  environment: {
    id: "5e1b3a0c-0000-4000-8000-000000000002",
    slug: "production",
    label: "Production",
  },
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

function routes(demandes: unknown[], apparies: unknown[], autres: Routes = {}): Routes {
  return {
    "GET /api/pairing/requests": { status: 200, body: demandes },
    "GET /api/pairing/peers": { status: 200, body: apparies },
    "GET /api/environments": { status: 200, body: ENVIRONNEMENTS },
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

  it("offers no way to move a pairing that already carries an environment", async () => {
    // Interdit explicite : le déplacer emporterait ses devices sans le dire. Ce geste
    // existe, et il s'appelle révoquer puis réapparier.
    monte(routes([], [APPARIE]));

    expect(await screen.findByText("Production")).toBeInTheDocument();
    // Resserré le 29/10/2026 : le motif disait /link|change/, et il attrapait depuis
    // « Change contact address » — qui ne déplace RIEN, c'est l'adresse où l'on joint la
    // stack, pas son environnement. Un test dont le filtre déborde finit par interdire
    // ce qu'il ne visait pas. On nomme donc les deux gestes qu'on refuse ici.
    expect(screen.queryByRole("button", { name: /link to an environment/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /change the environment/i })).toBeNull();
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
});
