import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { type Me, useLogout } from "./api/auth";
import { usePreferences } from "./api/preferences";
import { AuthGate } from "./auth/AuthGate";
import { readStoredCulture } from "./auth/visitorCulture";
import { ApiKeysScreen } from "./apiKeys/ApiKeysScreen";
import { CulturesScreen } from "./cultures/CulturesScreen";
import { GitConnectionsScreen } from "./gitConnections/GitConnectionsScreen";
import { HealthStatus } from "./health/HealthStatus";
import { applyLanguage } from "./i18n/i18n";
import { Topbar } from "./layout/Topbar";
import { type WorkspaceSelection, WorkspacesNav } from "./layout/WorkspacesNav";
import { ConnectorsScreen } from "./oidc/ConnectorsScreen";
import { ProfileScreen } from "./profile/ProfileScreen";
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
  | "apiKeys"
  | "health";
// Deux menus, dans cet ordre (Gael, 21/10/2026) : le global d'abord, ce que partagent tous
// les workspaces, puis les workspaces. L'ordre des écrans dans le global est voulu.
// Le menu Workspaces porte ses workspaces en sous-menu, et leurs vues en sous-sous-menu.
// Seuls figurent les écrans livrés ; parc, comptes et environnements viendront avec leurs tickets.
type Section = { title: string; pages: Page[] };
const SECTIONS: Section[] = [
  {
    title: "global",
    pages: ["cultures", "secrets", "gitConnections", "security", "oidc", "apiKeys", "health"],
  },
  { title: "workspaces", pages: ["workspaces"] },
];
const SCREENS: Record<Exclude<Page, "workspaces">, () => JSX.Element> = {
  security: SecurityServiceScreen,
  gitConnections: GitConnectionsScreen,
  oidc: ConnectorsScreen,
  cultures: CulturesScreen,
  secrets: SecretsScreen,
  apiKeys: ApiKeysScreen,
  health: HealthStatus,
};

/** Le portail de l'administrateur : seul compte qui ait des droits tant que les rôles manquent. */
function AdminPortal({ profile, onLeave }: { profile: ReactNode; onLeave: () => void }) {
  const { t } = useTranslation();
  const [page, setPageState] = useState<Page>("workspaces");
  // Tenue ici et non dans l'écran : le menu et l'écran montrent le même workspace.
  const [selection, setSelection] = useState<WorkspaceSelection>(null);
  // Menus repliés : tous ouverts au départ, pour que chaque écran reste en vue.
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());

  const Screen = page === "workspaces" ? null : SCREENS[page];

  // Le profil s'ouvre depuis la barre du haut ; tout choix dans le menu le referme.
  function setPage(next: Page) {
    onLeave();
    setPageState(next);
  }

  function openWorkspaces(next: WorkspaceSelection) {
    setPage("workspaces");
    setSelection(next);
  }

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
                {section.title === "workspaces" ? (
                  <WorkspacesNav
                    active={page === "workspaces"}
                    selection={selection}
                    onSelect={openWorkspaces}
                  />
                ) : (
                  section.pages.map((name) => (
                    <button
                      key={name}
                      type="button"
                      className="sidebar-link"
                      aria-current={page === name ? "page" : undefined}
                      onClick={() => setPage(name)}
                    >
                      {t(`app.nav.${name}`)}
                    </button>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </nav>
      <main className="content">
        {profile ?? (Screen === null ? (
          <WorkspacesScreen selection={selection} onSelect={openWorkspaces} />
        ) : (
          <Screen />
        ))}
      </main>
    </div>
  );
}

function SignedIn({ me }: { me: Me }) {
  const { t } = useTranslation();
  const logout = useLogout();
  const preferences = usePreferences();
  const [profileOpen, setProfileOpen] = useState(false);
  const language = preferences.data?.language;

  // La langue retenue pour le compte l'emporte ; sans choix, celle de l'écran de connexion.
  // Effet sur i18next, système extérieur à React : rien n'est recopié dans un état.
  useEffect(() => {
    if (preferences.isSuccess) {
      applyLanguage(language ?? readStoredCulture());
    }
  }, [preferences.isSuccess, language]);

  const profile = profileOpen ? <ProfileScreen me={me} /> : null;
  return (
    <>
      <Topbar>
        <button
          type="button"
          className="topbar-user topbar-button"
          aria-pressed={profileOpen}
          onClick={() => setProfileOpen(true)}
        >
          {me.email ?? me.username}
        </button>
        <button type="button" className="topbar-button" onClick={() => logout.mutate()}>
          {t("app.logout")}
        </button>
      </Topbar>
      {me.root_admin ? (
        <AdminPortal profile={profile} onLeave={() => setProfileOpen(false)} />
      ) : (
        // Authentifié n'est pas autorisé : sans rôle, rien d'autre que son profil ne s'ouvre.
        <div className="narrow">
          {profile ?? (
            <p className="alert" role="status">
              {t("app.noRights", { directory: me.directory ?? "" })}
            </p>
          )}
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
