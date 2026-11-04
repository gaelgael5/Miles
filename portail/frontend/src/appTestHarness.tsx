import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "./App";
import "./i18n/i18n";

/**
 * Le harnais des gardes de l'application : ce que les `App*.test.tsx` partagent.
 *
 * Extrait le 3 novembre 2026 (enabler `82ec7d76`), quand `App.test.tsx` a dépassé la
 * limite de 300 lignes du dépôt. Ce n'est pas un fichier de test : il ne porte aucune
 * assertion et aucun cycle de vie — `afterEach` reste dans chaque fichier de test, où il
 * s'applique à la suite qui le déclare.
 */
export function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

/**
 * Déplie un groupe du menu. Tous sont REPLIÉS au chargement depuis le 30/10/2026 : un
 * groupe fermé est `hidden`, donc ses entrées n'ont aucun rôle accessible, et c'est
 * voulu — un lecteur d'écran ne doit pas annoncer ce que l'œil ne voit pas.
 */
export async function openMenu(name: string) {
  const bouton = await screen.findByRole("button", { name });
  // Jamais de bascule aveugle : un groupe déjà ouvert serait refermé par le clic.
  if (bouton.getAttribute("aria-expanded") === "false") {
    fireEvent.click(bouton);
  }
}

export const BRANCHES = [
  { slug: "atelier", label: "atelier", branch: "back/retrait/atelier", base: true },
  { slug: "essai", label: "Essai Gael", branch: "back/retrait/essai", base: false },
];

export const ADMIN = {
  "GET /api/bootstrap/status": { status: 200, body: { admin_declared: true } },
  "GET /api/auth/me": {
    status: 200,
    body: {
      kind: "local_admin",
      username: "admin",
      email: "a@b.c",
      directory: null,
      root_admin: true,
    },
  },
  "GET /api/health": { status: 200, body: {} },
  "GET /api/workspaces": { status: 200, body: [] },
};
