import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useLogout } from "./api/auth";
import { AuthGate } from "./auth/AuthGate";
import { CulturesScreen } from "./cultures/CulturesScreen";
import { HealthStatus } from "./health/HealthStatus";
import { ConnectorsScreen } from "./oidc/ConnectorsScreen";
import { SecretsScreen } from "./secrets/SecretsScreen";
import { SecurityServiceScreen } from "./security/SecurityServiceScreen";

type Page = "home" | "secrets" | "cultures" | "oidc" | "security";
const PAGES: Page[] = ["home", "secrets", "cultures", "oidc", "security"];

/** Le portail de l'administrateur : seul compte qui ait des droits tant que les rôles manquent. */
function AdminPortal() {
  const { t } = useTranslation();
  const [page, setPage] = useState<Page>("home");
  return (
    <>
      <nav>
        {PAGES.map((name) => (
          <button
            key={name}
            type="button"
            aria-current={page === name ? "page" : undefined}
            onClick={() => setPage(name)}
          >
            {t(`app.nav.${name}`)}
          </button>
        ))}
      </nav>
      {page === "home" && <HealthStatus />}
      {page === "secrets" && <SecretsScreen />}
      {page === "cultures" && <CulturesScreen />}
      {page === "oidc" && <ConnectorsScreen />}
      {page === "security" && <SecurityServiceScreen />}
    </>
  );
}

export function App() {
  const { t } = useTranslation();
  const logout = useLogout();
  return (
    <main>
      <h1>{t("app.title")}</h1>
      <AuthGate>
        {(me) => (
          <>
            <p>
              {t("app.signedInAs", { username: me.username })}{" "}
              <button type="button" onClick={() => logout.mutate()}>
                {t("app.logout")}
              </button>
            </p>
            {me.kind === "oidc" ? (
              // Authentifié n'est pas autorisé : sans rôle, rien d'autre ne s'ouvre.
              <p role="status">{t("app.noRights", { directory: me.directory ?? "" })}</p>
            ) : (
              <AdminPortal />
            )}
          </>
        )}
      </AuthGate>
    </main>
  );
}
