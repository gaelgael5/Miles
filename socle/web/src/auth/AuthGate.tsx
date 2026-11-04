import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { type Me, useBootstrapStatus, useMe } from "../api/auth";
import { Topbar } from "../layout/Topbar";
import { BootstrapScreen } from "./BootstrapScreen";
import { LoginScreen } from "./LoginScreen";

interface AuthGateProps {
  children: (me: Me) => ReactNode;
}

/** Amorçage, connexion ou portail : l'écran suit l'état que rend le serveur. */
export function AuthGate({ children }: AuthGateProps) {
  const { t } = useTranslation();
  const status = useBootstrapStatus();
  const declared = status.data?.admin_declared === true;
  const me = useMe(declared);

  if (me.data !== null && me.data !== undefined && declared) {
    return <>{children(me.data)}</>;
  }
  // Hors portail (chargement, amorçage, connexion) : une colonne centrée, sans navigation.
  let screen: ReactNode;
  if (status.isPending || (declared && me.isPending)) {
    screen = <p className="muted" role="status">{t("auth.loading")}</p>;
  } else if (status.isError || me.isError) {
    screen = <p className="alert" role="alert">{t("auth.unreachable")}</p>;
  } else if (!declared) {
    screen = <BootstrapScreen />;
  } else {
    screen = <LoginScreen />;
  }
  return (
    <>
      <Topbar>
        {!declared && status.isSuccess && (
          <span className="topbar-user">{t("app.freshInstall")}</span>
        )}
      </Topbar>
      <div className="narrow">{screen}</div>
    </>
  );
}
