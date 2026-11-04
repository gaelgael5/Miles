import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { App } from "./App";
import "./i18n/i18n";

const ADMIN = {
  kind: "local_admin",
  username: "admin",
  subject: "admin",
  email: "admin@environnement.invalid",
  directory: null,
  root_admin: true,
};
const SANTE = {
  status: "ok",
  database: "up",
  schema_version: 8,
  expected_schema_version: 8,
};
// Les écrans du menu, et la requête qui prouve que chacun s'est réellement ouvert.
// `titre` n'est porté que par le service d'ingestion : sa requête d'état est désormais
// faite par le MENU lui-même, qui y lit les sources à lister, donc la trouver ne prouve
// plus que l'écran s'est ouvert. C'est son titre qui le prouve.
const ECRANS: { nom: string; libelle: string; appel: string; titre?: string }[] = [
  { nom: "pairing", libelle: "Pairing", appel: "GET /api/identity/pairing/state" },
  { nom: "storages", libelle: "Storage spaces", appel: "GET /api/storages" },
  { nom: "apikeys", libelle: "API keys", appel: "GET /api/api-keys" },
  {
    nom: "ingestion",
    libelle: "Ingestion service",
    appel: "GET /api/ingestion/health",
    titre: "Ingestion service",
  },
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
  "GET /api/identity/pairing/state": {
    status: 200,
    body: { state: "non_apparie", attempt: null, peer: null },
  },
  "GET /api/secrets": { status: 200, body: [] },
  "GET /api/secret-types": { status: 200, body: { types: ["OIDC_CLIENT_SECRET"] } },
  "GET /api/oidc/connectors": { status: 200, body: [] },
  // Un storage réel et non une liste vide : un écran qui n'a rien à montrer rend une
  // explication, pas son titre, et la garde du menu vérifie justement le titre.
  "GET /api/storages": {
    status: 200,
    body: [
      {
        name: "accounts",
        label: "Accounts",
        model: "pudo/accounts",
        schema_name: "pudo",
        table_name: "accounts",
        keys: ["$.AccountId"],
        projections: [
          {
            column: "contact_phone",
            path: "$.Contact.Phone",
            kind: "string",
            sql_type: "text",
          },
        ],
        indexes: [{ name: "tel", columns: ["contact_phone"] }],
        applied_at: "2026-11-02T07:08:26Z",
        version_number: 1,
        refusal: null,
        refusal_detail: null,
      },
    ],
  },
  "GET /api/api-keys": { status: 200, body: [] },
  // Une version servie et un point d'entrée réels : un écran qui n'a rien à montrer
  // rend une explication, pas son titre, et la garde du menu vérifie le titre.
  "GET /api/ingestion/health": {
    status: 200,
    body: {
      version_number: 1,
      version_commit: "abcdef1234567890",
      version_served_at: "2026-11-02T08:00:00Z",
      endpoints: [
        {
          source: "comptes-pudo",
          storage: "accounts",
          entry_model: "pudo/accounts",
          mode: "tableau",
          path: "/ingest/comptes-pudo/tableau",
          served: true,
        },
      ],
      unreadable_sources: [],
      active_keys: 1,
      never_used_keys: 0,
      deposits_total: 0,
      deposits_recent: 0,
      last_deposit_at: null,
      bulk_modes: [],
    },
  },
  "GET /api/ingestion/calls": {
    status: 200,
    body: { calls: [], total: 0, page: 1, page_size: 50, sources: ["comptes-pudo"] },
  },
  // La page d'une source lit les méthodes et le contrat publié : sans ces deux routes,
  // son ouverture rendrait un refus de lecture au lieu de son contrat.
  "GET /api/ingestion/methods": {
    status: 200,
    body: {
      methods: [
        {
          source: "comptes-pudo",
          storage: "accounts",
          entry_model: "pudo/accounts",
          mode: "tableau",
          path: "/ingest/comptes-pudo/tableau",
          operation: "/ingest/{source}/{mode}",
          served: true,
          request_schema: { type: "object" },
          model_refusal: null,
          example: [{ code: "code" }],
        },
      ],
    },
  },
  "GET /api/ingestion/contract": { status: 200, body: {} },
  "GET /api/api-keys/sources": { status: 200, body: { sources: ["comptes-pudo"] } },
  "GET /api/auth/cultures": { status: 200, body: [{ code: "en-US", label_native: "English" }] },
};

describe("App du module d'environnement", () => {
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

    expect(await screen.findByText("Environment module")).toBeInTheDocument();
    expect(screen.getByText("Miles")).toBeInTheDocument();
  });

  it.each(ECRANS)(
    "ouvre l'écran $nom depuis son entrée de menu",
    async ({ libelle, appel, titre }) => {
      const calls = monte(CONNECTE);
      const menu = within(await screen.findByRole("navigation"));

      fireEvent.click(menu.getByRole("button", { name: libelle }));

      // L'écran s'est ouvert ET a parlé au serveur : une entrée de menu qui ne mène
      // nulle part laisserait ce bouton sans appel, tout en paraissant verte.
      if (titre === undefined) {
        await screen.findByRole("heading", { level: 1 });
      } else {
        expect(await screen.findByRole("heading", { level: 1, name: titre })).toBeInTheDocument();
      }
      expect(calls.map((c) => c.key)).toContain(appel);
    },
  );

  it("liste les sources servies sous le service d'ingestion, et ouvre leur page", async () => {
    const calls = monte(CONNECTE);
    const menu = within(await screen.findByRole("navigation"));

    // La source vient de la version SERVIE, pas d'une liste tenue dans le code : elle
    // n'apparaît qu'une fois l'état du service lu.
    fireEvent.click(await menu.findByRole("button", { name: "comptes-pudo" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "comptes-pudo" }),
    ).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toContain("GET /api/ingestion/methods");
    // La page du service n'est plus celle qui est ouverte : son titre a cédé la place.
    expect(screen.queryByRole("heading", { level: 1, name: "Ingestion service" })).toBeNull();
  });

  it("quitte la source quand on choisit un autre écran", async () => {
    // Sans cette remise à zéro, l'écran choisi serait masqué par la source restée
    // ouverte, et le menu montrerait deux entrées courantes.
    monte(CONNECTE);
    const menu = within(await screen.findByRole("navigation"));
    fireEvent.click(await menu.findByRole("button", { name: "comptes-pudo" }));
    await screen.findByRole("heading", { level: 1, name: "comptes-pudo" });

    fireEvent.click(menu.getByRole("button", { name: "Cultures" }));

    expect(screen.queryByRole("heading", { level: 1, name: "comptes-pudo" })).toBeNull();
  });

  it("n'a aucune entrée de menu de plus que d'écrans déclarés et de sources servies", async () => {
    monte(CONNECTE);
    const menu = within(await screen.findByRole("navigation"));
    await menu.findByRole("button", { name: "comptes-pudo" });

    // La garde du ticket : un écran déclaré mais absent du menu est inatteignable, et
    // une entrée de menu sans écran mène dans le vide. Ici les deux viennent de la même
    // déclaration, et ce test interdit qu'on les redouble. Les sources s'y ajoutent, une
    // par source de la version servie — la version d'essai n'en déclare qu'une.
    expect(menu.getAllByRole("button")).toHaveLength(ECRANS.length + 1);
  });

  it("ouvre le profil depuis la barre du haut", async () => {
    monte(CONNECTE);

    fireEvent.click(await screen.findByRole("button", { name: "admin@environnement.invalid" }));

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
