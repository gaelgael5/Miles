import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "./App";
import "./i18n/i18n";

const ADMIN = {
  kind: "local_admin",
  username: "admin",
  subject: "admin",
  email: "admin@enrolement.invalid",
  directory: null,
  root_admin: true,
};
const SANTE = {
  status: "ok",
  database: "up",
  schema_version: 7,
  expected_schema_version: 7,
};
// Les écrans du menu, et la requête qui prouve que chacun s'est réellement ouvert.
const ECRANS: { nom: string; libelle: string; appel: string }[] = [
  { nom: "pairing", libelle: "Pairing", appel: "GET /api/pairing/requests" },
  { nom: "environments", libelle: "Environments", appel: "GET /api/environments" },
  // La requête porte sa chaîne de paramètres : l'écran borne toujours sa page, et la
  // garde compare la clé EXACTE — un écran qui demanderait tout le journal d'un coup
  // ferait donc rougir celle-ci.
  {
    nom: "events",
    libelle: "Event journal",
    appel: "GET /api/events?page=1&size=50",
  },
  { nom: "cultures", libelle: "Cultures", appel: "GET /api/cultures" },
  { nom: "secrets", libelle: "Secrets", appel: "GET /api/secrets" },
  { nom: "oidc", libelle: "OIDC connectors", appel: "GET /api/oidc/connectors" },
  { nom: "health", libelle: "Service status", appel: "GET /api/health" },
];

const ENVIRONNEMENT = {
  id: "env-1",
  slug: "recette-nord",
  label: "Recette nord",
  created_at: "2026-11-01T08:00:00Z",
  updated_at: "2026-11-01T08:00:00Z",
  paired_base_url: null,
  designated_base_url: null,
  workspace_id: null,
};

function monte(routes: Routes) {
  const calls = mockApi(routes);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <App />
    </QueryClientProvider>,
  );
  return calls;
}

const CONNECTE: Routes = {
  "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } },
  "GET /api/auth/me": { status: 200, body: ADMIN },
  "GET /api/auth/me/preferences": { status: 200, body: { language: null } },
  "GET /api/health": { status: 200, body: SANTE },
  "GET /api/cultures": { status: 200, body: [] },
  // Un event réel et non une liste vide : un écran qui n'a rien à montrer rend une
  // explication, pas son titre, et la garde du menu vérifie justement le titre.
  "GET /api/events": {
    status: 200,
    body: {
      events: [
        {
          id: "11111111-1111-4111-8111-111111111111",
          type: "secret.created",
          functional_at: "2026-11-02T10:21:29Z",
          functional_at_source: "caller",
          written_at: "2026-11-02T10:21:29Z",
          author_directory: "local",
          author_subject: "admin",
          properties: {},
          objects: [],
        },
      ],
      total: 1,
      page: 1,
      size: 50,
      window: {
        start: "2026-10-27T12:00:00Z",
        end: "2026-11-03T12:00:00Z",
        defaulted: true,
      },
      missing_sequences: [],
    },
  },
  "GET /api/pairing/requests": { status: 200, body: [] },
  "GET /api/pairing/peers": { status: 200, body: [] },
  "GET /api/environments": { status: 200, body: [] },
  "GET /api/secrets": { status: 200, body: [] },
  "GET /api/secret-types": { status: 200, body: { types: ["OIDC_CLIENT_SECRET"] } },
  "GET /api/oidc/connectors": { status: 200, body: [] },
  "GET /api/auth/cultures": { status: 200, body: [{ code: "en-US", label_native: "English" }] },
};

describe("App du module d'enrôlement", () => {
  it("replie le menu depuis la barre du haut", async () => {
    // Le bouton est dans la BARRE, le menu dans le corps : deux composants que l'App
    // rend côte à côte, et c'est elle qui les relie. Sans cette garde, un produit peut
    // oublier de poser la classe ou l'identifiant, et le bouton ne commanderait rien.
    monte(CONNECTE);
    const replier = await screen.findByRole("button", { name: "Collapse or expand the menu" });
    expect(replier).toHaveAttribute("aria-controls", screen.getByRole("navigation").id);

    fireEvent.click(replier);

    expect(screen.getByRole("navigation")).toHaveClass("sidebar-collapsed");
  });

  it("conduit à l'écran d'amorçage sur une installation où aucun administrateur n'existe", async () => {
    monte({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: false } },
    });

    expect(
      await screen.findByRole("heading", { name: "Create the administrator account" }),
    ).toBeInTheDocument();
    // L'amorçage et lui seul : aucun menu, aucun écran de gestion n'est atteignable.
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("demande la connexion quand un administrateur existe déjà", async () => {
    monte({
      "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } },
      "GET /api/auth/me": { status: 401, body: { detail: "session_requise" } },
      "GET /api/auth/oidc/connectors?culture=en-US": { status: 200, body: [] },
      "GET /api/auth/cultures": { status: 200, body: [{ code: "en-US", label_native: "English" }] },
    });

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    // L'écran d'amorçage s'est refermé : il ne se rouvre pas une fois l'administrateur créé.
    expect(
      screen.queryByRole("heading", { name: "Create the administrator account" }),
    ).not.toBeInTheDocument();
  });

  it("porte le sous-titre du produit, distinct de celui du portail", async () => {
    monte(CONNECTE);

    expect(await screen.findByText("Enrolment module")).toBeInTheDocument();
    expect(screen.getByText("Miles")).toBeInTheDocument();
  });

  it.each(ECRANS)(
    "ouvre l'écran $nom depuis son entrée de menu",
    async ({ libelle, appel }) => {
      const calls = monte(CONNECTE);
      const menu = within(await screen.findByRole("navigation"));

      fireEvent.click(menu.getByRole("button", { name: libelle }));

      // L'écran s'est ouvert ET a parlé au serveur : une entrée de menu qui ne mène
      // nulle part laisserait ce bouton sans appel, tout en paraissant verte.
      await screen.findByRole("heading", { level: 1 });
      expect(calls.map((c) => c.key)).toContain(appel);
    },
  );

  it("n'a aucune entrée de menu de plus que d'écrans déclarés", async () => {
    monte(CONNECTE);
    const nav = await screen.findByRole("navigation");

    // La garde du ticket : un écran déclaré mais absent du menu est inatteignable, et
    // une entrée de menu sans écran mène dans le vide. Ici les deux viennent de la même
    // déclaration, et ce test interdit qu'on les redouble. Les deux en-têtes de section
    // sont des boutons depuis qu'elles se replient : on compte donc les LIENS, qui sont
    // seuls à mener quelque part.
    expect(nav.querySelectorAll("button.sidebar-link")).toHaveLength(ECRANS.length);
    expect(nav.querySelectorAll("button.sidebar-section")).toHaveLength(2);
  });

  it("replie une section du menu, et la rouvre", async () => {
    // Le défaut corrigé le 01/11/2026 : la feuille de style du socle dessine un chevron
    // sur une section, et celles-ci ne se repliaient pas — le menu montrait un geste
    // qu'il ne servait pas.
    monte(CONNECTE);
    const nav = await screen.findByRole("navigation");
    const section = within(nav).getByRole("button", { name: "Global" });

    fireEvent.click(section);

    expect(section).toHaveAttribute("aria-expanded", "false");
    expect(within(nav).queryByRole("button", { name: "Pairing" })).toBeNull();

    fireEvent.click(section);

    expect(within(nav).getByRole("button", { name: "Pairing" })).toBeInTheDocument();
  });

  it("ne liste sous Workspaces que ceux qu'un environnement héberge", async () => {
    monte({
      ...CONNECTE,
      "GET /api/environments": {
        status: 200,
        body: [
          { ...ENVIRONNEMENT, workspace_id: "ams" },
          { ...ENVIRONNEMENT, id: "env-2", slug: "sans-workspace", workspace_id: null },
        ],
      },
    });
    const nav = within(await screen.findByRole("navigation"));

    expect(await nav.findByRole("button", { name: /ams/ })).toBeInTheDocument();
    // Un environnement sans workspace n'a rien à héberger : il n'a pas de page.
    expect(nav.queryByRole("button", { name: /sans-workspace/ })).toBeNull();
  });

  it("ouvre la page du workspace hébergé, puis ses comptes", async () => {
    monte({
      ...CONNECTE,
      "GET /api/environments": {
        status: 200,
        body: [{ ...ENVIRONNEMENT, workspace_id: "ams" }],
      },
    });
    const nav = within(await screen.findByRole("navigation"));

    fireEvent.click(await nav.findByRole("button", { name: /ams/ }));

    expect(await screen.findByRole("heading", { level: 1, name: "ams" })).toBeInTheDocument();
    // L'environnement qui l'héberge est nommé sur la page, pas seulement dans le menu —
    // et UNE SEULE FOIS (Gael, 05/11/2026) : le chapeau le dit en toutes lettres, et la
    // carte de provenance le répétait deux lignes plus bas en libellé de colonne.
    expect(within(screen.getByRole("main")).getAllByText(/Recette nord/)).toHaveLength(1);

    fireEvent.click(nav.getByRole("button", { name: "Accounts" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Accounts" }),
    ).toBeInTheDocument();
  });

  it("ouvre le profil depuis la barre du haut", async () => {
    monte(CONNECTE);

    fireEvent.click(await screen.findByRole("button", { name: "admin@enrolement.invalid" }));

    expect(await screen.findByRole("heading", { name: "My profile" })).toBeInTheDocument();
    expect(screen.getByText("Root administrator")).toBeInTheDocument();
  });

  it("n'ouvre rien à une session sans droit", async () => {
    monte({
      ...CONNECTE,
      "GET /api/auth/me": {
        status: 200,
        body: { ...ADMIN, kind: "oidc", directory: "annuaire-maison", root_admin: false },
      },
    });

    // Attendu par le texte et non par le rôle : « Checking your session… » porte le
    // même rôle « status » et serait trouvé en premier.
    expect(await screen.findByText(/no right is granted/)).toBeInTheDocument();
    // Aucun accès par défaut : le menu n'existe pas pour cette session.
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});
