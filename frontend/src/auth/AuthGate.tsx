import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { type Me, useBootstrapStatus, useMe } from "../api/auth";
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

  if (status.isPending || (declared && me.isPending)) {
    return <p role="status">{t("auth.loading")}</p>;
  }
  if (status.isError || me.isError) {
    return <p role="alert">{t("auth.unreachable")}</p>;
  }
  if (!declared) {
    return <BootstrapScreen />;
  }
  if (me.data === null || me.data === undefined) {
    return <LoginScreen />;
  }
  return <>{children(me.data)}</>;
}
