import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

/** Barre supérieure des maquettes : la marque à gauche, la personne connectée à droite. */
export function Topbar({ children }: { children?: ReactNode }) {
  const { t } = useTranslation();
  return (
    <header className="topbar">
      <span className="topbar-brand">{t("app.brand")}</span>
      <span className="topbar-sub">{t("app.sub")}</span>
      <span className="topbar-spacer" />
      {children}
    </header>
  );
}
