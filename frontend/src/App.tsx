import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type Me, useLogout } from "./api/auth";
import { AuthGate } from "./auth/AuthGate";
import { CertificatesScreen } from "./certificates/CertificatesScreen";
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
  | "certificates"
  | "oidc"
  | "cultures"
  | "secrets"
  | "health";
// Sections de la navigation des maquettes : l'organisation d'abord, les réglages ensuite.
// Seuls figurent les écrans livrés ; parc, comptes et environnements viendront avec leurs tickets.
const SECTIONS: { title: string; pages: Page[] }[] = [
  { title: "organisation", pages: ["workspaces"] },
  { title: "settings", pages: [
      "security",
      "gitConnections",
      "certificates",
      "oidc",
      "cultures",
      "secrets",
      "health",
    ],
   },
];
const SCREENS: Record<Page, () => JSX.Element> = {
  workspaces: WorkspacesScreen,
  security: SecurityServiceScreen,
  gitConnections: GitConnectionsScreen,
  certificates: CertificatesScreen,
  oidc: ConnectorsScreen,
  cultures: CulturesScreen,
  secrets: SecretsScreen,
  health: HealthStatus,
};

/** Le portail de l'administrateur : seul compte qui ait des droits tant que les rôles manquent. */
function AdminPortal() {
  const { t } = useTranslation();
  const [page, setPage] = useState<Page>("workspaces");
  const Screen = SCREENS[page];
  return (
    <div className="body">
      <nav className="sidebar" aria-label={t("app.navigation")}>
        {SECTIONS.map((section) => (
          <div key={section.title}>
            <div className="sidebar-section">{t(`app.sections.${section.title}`)}</div>
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
        ))}
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
