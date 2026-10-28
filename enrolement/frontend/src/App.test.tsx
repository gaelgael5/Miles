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
  "GET /api/pairing/requests": { status: 200, body: [] },
  "GET /api/pairing/peers": { status: 200, body: [] },
  "GET /api/environments": { status: 200, body: [] },
  "GET /api/secrets": { status: 200, body: [] },
  "GET /api/secret-types": { status: 200, body: { types: ["OIDC_CLIENT_SECRET"] } },
  "GET /api/oidc/connectors": { status: 200, body: [] },
  "GET /api/auth/cultures": { status: 200, body: [{ code: "en-US", label_native: "English" }] },
};

describe("App du module d'enrôlement", () => {
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
    const menu = within(await screen.findByRole("navigation"));

    // La garde du ticket : un écran déclaré mais absent du menu est inatteignable, et
    // une entrée de menu sans écran mène dans le vide. Ici les deux viennent de la même
    // déclaration, et ce test interdit qu'on les redouble.
    expect(menu.getAllByRole("button")).toHaveLength(ECRANS.length);
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
