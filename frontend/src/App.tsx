import { useTranslation } from "react-i18next";

import { useLogout } from "./api/auth";
import { AuthGate } from "./auth/AuthGate";
import { HealthStatus } from "./health/HealthStatus";

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
            <HealthStatus />
          </>
        )}
      </AuthGate>
    </main>
  );
}
