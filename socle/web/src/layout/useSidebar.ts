import { useState } from "react";

const STORAGE_KEY = "miles.sidebarCollapsed";

/**
 * Identifiant de la navigation, partagé par le bouton et le menu.
 *
 * Au socle et non dans chaque produit : c'est `aria-controls` du bouton qui le désigne,
 * et deux constantes de même valeur dans deux endroits auraient divergé au premier
 * renommage fait d'un seul côté — le bouton aurait alors annoncé qu'il commande une
 * région qui n'existe pas, sans que rien ne le signale.
 */
export const NAV_ID = "miles-nav";

export interface Sidebar {
  collapsed: boolean;
  toggle: () => void;
  /** Classe du `<nav>` : au produit de la poser, c'est lui qui rend son menu. */
  navClassName: string;
}

/** Choix mémorisé sur ce navigateur ; le stockage peut être refusé (navigation privée). */
function readStored(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function store(collapsed: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(collapsed));
  } catch {
    // Choix non mémorisé : il vaut pour cette page, et c'est un confort, pas un droit.
  }
}

/**
 * Le menu latéral replié ou non (Gael, 05/11/2026), dans les trois back-offices.
 *
 * L'état est ici, et non dans un contexte : le bouton est dans la barre du haut et le
 * menu dans le corps, deux composants que chaque produit rend côte à côte — il le tient
 * donc déjà, et un contexte n'aurait ajouté qu'un fournisseur à oublier.
 *
 * Mémorisé d'une page à l'autre : qui replie le menu travaille à l'étroit, et le
 * redéplier à chaque rechargement défait le geste à chaque fois.
 */
export function useSidebar(): Sidebar {
  const [collapsed, setCollapsed] = useState(readStored);
  return {
    collapsed,
    toggle: () => {
      // Hors de la fonction de mise à jour : React peut l'appeler deux fois, et un
      // effet de bord n'y a rien à faire — même inoffensif, il apprend à en mettre.
      const suivant = !collapsed;
      setCollapsed(suivant);
      store(suivant);
    },
    navClassName: collapsed ? "sidebar sidebar-collapsed" : "sidebar",
  };
}
