import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useLogout } from "./api/auth";
import { AuthGate } from "./auth/AuthGate";
import { CulturesScreen } from "./cultures/CulturesScreen";
import { HealthStatus } from "./health/HealthStatus";
import { SecretsScreen } from "./secrets/SecretsScreen";

type Page = "home" | "secrets" | "cultures";
const PAGES: Page[] = ["home", "secrets", "cultures"];

export function App() {
  const { t } = useTranslation();
  const logout = useLogout();
  const [page, setPage] = useState<Page>("home");
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
          </>
        )}
      </AuthGate>
    </main>
  );
}
