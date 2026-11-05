import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { NAV_ID, type Sidebar } from "./useSidebar";

/**
 * Barre supérieure des maquettes : la marque à gauche, la personne connectée à droite.
 *
 * Le bouton de repli du menu est le PREMIER élément (Gael, 05/11/2026) : c'est le coin
 * haut gauche, au-dessus du menu qu'il commande. Sans `sidebar`, la barre est celle
 * d'avant — les écrans hors back-office (amorçage, connexion) n'ont aucun menu à replier.
 */
export function Topbar({ sidebar, children }: { sidebar?: Sidebar; children?: ReactNode }) {
  const { t } = useTranslation();
  return (
    <header className="topbar">
      {sidebar !== undefined && (
        <button
          type="button"
          className="topbar-nav-toggle"
          // L'état est DIT, pas seulement dessiné : un lecteur d'écran annonce « replié »
          // sur le même bouton, et `aria-controls` désigne le menu qu'il commande.
          aria-expanded={!sidebar.collapsed}
          aria-controls={NAV_ID}
          aria-label={t("app.toggleNav")}
          title={t("app.toggleNav")}
          onClick={sidebar.toggle}
        >
          {/* Le panneau latéral, dessiné : un cadre et son volet de gauche. `aria-hidden`
              parce que le nom du bouton est déjà porté par `aria-label` — annoncer deux
              fois la même chose fait lire le bouton deux fois. */}
          <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
            <rect
              x="1.5"
              y="2.5"
              width="13"
              height="11"
              rx="2"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
            />
            <line x1="6" y1="2.5" x2="6" y2="13.5" stroke="currentColor" strokeWidth="1.4" />
          </svg>
        </button>
      )}
      <span className="topbar-brand">{t("app.brand")}</span>
      <span className="topbar-sub">{t("app.sub")}</span>
      <span className="topbar-spacer" />
      {children}
    </header>
  );
}
