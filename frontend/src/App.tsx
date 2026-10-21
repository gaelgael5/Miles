import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type Me, useLogout } from "./api/auth";
import { AuthGate } from "./auth/AuthGate";
import { CulturesScreen } from "./cultures/CulturesScreen";
import { GitConnectionsScreen } from "./gitConnections/GitConnectionsScreen";
import { HealthStatus } from "./health/HealthStatus";
import { Topbar } from "./layout/Topbar";
import { ConnectorsScreen } from "./oidc/ConnectorsScreen";
import { SecretsScreen } from "./secrets/SecretsScreen";
import { SecurityServiceScreen } from "./security/SecurityServiceScreen";
import { WorkspacesScreen } from "./workspaces/WorkspacesScreen";

type Page =
  | "workspaces"
  | "security"
  | "gitConnections"
  | "oidc"
  | "cultures"
  | "secrets"
  | "health";
// Deux menus, dans cet ordre (Gael, 21/10/2026) : le global d'abord, ce que partagent tous
// les workspaces, puis les workspaces. L'ordre des écrans dans le global est voulu.
// Un menu sans sous-menu (`page`) est lui-même le lien : un titre « Workspaces » au-dessus
// d'un unique lien « Workspaces » ferait doublon.
// Seuls figurent les écrans livrés ; parc, comptes et environnements viendront avec leurs tickets.
type Section = { title: string; pages: Page[] } | { title: string; page: Page };
const SECTIONS: Section[] = [
  {
    title: "global",
    pages: ["cultures", "secrets", "gitConnections", "security", "oidc", "health"],
  },
  { title: "workspaces", page: "workspaces" },
];
const SCREENS: Record<Page, () => JSX.Element> = {
  workspaces: WorkspacesScreen,
  security: SecurityServiceScreen,
  gitConnections: GitConnectionsScreen,
  oidc: ConnectorsScreen,
  cultures: CulturesScreen,
  secrets: SecretsScreen,
  health: HealthStatus,
};

/** Le portail de l'administrateur : seul compte qui ait des droits tant que les rôles manquent. */
function AdminPortal() {
  const { t } = useTranslation();
  const [page, setPage] = useState<Page>("workspaces");
  // Menus repliés : tous ouverts au départ, pour que chaque écran reste en vue.
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const Screen = SCREENS[page];

  function toggle(title: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (!next.delete(title)) {
        next.add(title);
      }
      return next;
    });
  }

  return (
    <div className="body">
      <nav className="sidebar" aria-label={t("app.navigation")}>
        {SECTIONS.map((section) => {
          if ("page" in section) {
            return (
              <div key={section.title} className="sidebar-group">
                <button
                  type="button"
                  className="sidebar-section sidebar-section-link"
                  aria-current={page === section.page ? "page" : undefined}
                  onClick={() => setPage(section.page)}
                >
                  {t(`app.sections.${section.title}`)}
                </button>
              </div>
            );
          }
          const open = !collapsed.has(section.title);
          const listId = `sidebar-${section.title}`;
          return (
            <div key={section.title} className="sidebar-group">
              <button
                type="button"
                className="sidebar-section"
                aria-expanded={open}
                aria-controls={listId}
                onClick={() => toggle(section.title)}
              >
                {t(`app.sections.${section.title}`)}
              </button>
              <div id={listId} hidden={!open}>
                {section.pages.map((name) => (
                  <button
                    key={name}
                    type="button"
                    className="sidebar-link"
                    aria-current={page === name ? "page" : undefined}
                    onClick={() => setPage(name)}
                  >
                    {t(`app.nav.${name}`)}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </nav>
      <main className="content">
        <Screen />
      </main>
    </div>
  );
}

function SignedIn({ me }: { me: Me }) {
  const { t } = useTranslation();
  const logout = useLogout();
  return (
    <>
      <Topbar>
        <span className="topbar-user">{me.email ?? me.username}</span>
        <button type="button" className="topbar-button" onClick={() => logout.mutate()}>
          {t("app.logout")}
        </button>
      </Topbar>
      {me.root_admin ? (
        <AdminPortal />
      ) : (
        // Authentifié n'est pas autorisé : sans rôle, rien d'autre ne s'ouvre.
        <div className="narrow">
          <p className="alert" role="status">
            {t("app.noRights", { directory: me.directory ?? "" })}
          </p>
        </div>
      )}
    </>
  );
}

export function App() {
  return (
    <div className="shell">
      <AuthGate>{(me) => <SignedIn me={me} />}</AuthGate>
    </div>
  );
}
