import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";

import type { WorkspaceCultures } from "../api/workspaceCultures";
import type { WorkspaceSelection } from "../layout/WorkspacesNav";

import type { Routes } from "@miles/socle-web/testing";
import { WorkspacesScreen } from "./WorkspacesScreen";

export const REPORT = {
  branch: "miles-verification-0a1b2c3d",
  tag: "miles-verification-0a1b2c3d",
  checks: [
    { right: "lire", ok: true, reason: null },
    { right: "creer_branche", ok: true, reason: null },
    { right: "pousser", ok: true, reason: null },
    { right: "poser_tag", ok: true, reason: null },
    { right: "supprimer_branche", ok: false, reason: "droit_refuse" },
  ],
  residual_branch: "miles-verification-0a1b2c3d",
  residual_tag: null,
  existing_branches: 0,
  initialized_branch: "main",
  all_passed: false,
};
export const PASSED = {
  ...REPORT,
  all_passed: true,
  residual_branch: null,
  checks: REPORT.checks.map((c) => ({ ...c, ok: true, reason: null })),
};
// Juste créé : le nom seul, aucun dépôt.
export const BARE = {
  id: "retrait",
  name: "Retrait de colis",
  repo_url: null,
  git_connection_id: null,
  security_service_id: null,
  last_check: null,
  last_check_at: null,
  created_at: "2026-10-21T10:00:00Z",
  work_branch: null,
};
export const CONFIGURED = {
  ...BARE,
  repo_url: "https://github.com/acme/retrait.git",
  git_connection_id: "acme",
  last_check: PASSED,
  last_check_at: "2026-10-21T10:05:00Z",
};
export const CONNECTION = {
  id: "acme",
  label: "GitHub Acme",
  base_url: "https://github.com/acme",
  token_secret_slug: "gh",
  workspaces: [],
  created_at: "2026-10-21T09:00:00Z",
  updated_at: "2026-10-21T09:00:00Z",
};
/** Catalogue des cultures : le sélecteur en propose la TOTALITÉ, pas les seules actives. */
export const CATALOGUE = [
  { code: "fr-FR", label_en: "French (France)", label_native: "français (France)", active: true },
  { code: "en-US", label_en: "English (US)", label_native: "English (US)", active: true },
  { code: "ar-MA", label_en: "Arabic (Morocco)", label_native: "العربية (المغرب)", active: false },
  { code: "th-TH", label_en: "Thai (Thailand)", label_native: "ไทย (ไทย)", active: false },
];
export const WORKSPACE_CULTURES: WorkspaceCultures = {
  default: "fr-FR",
  additional: ["ar-MA"],
  // ar-MA s'écrit de droite à gauche : c'est la culture discriminante du jeu d'essai,
  // sans quoi aucun test ne verrait la différence entre les deux sens.
  directions: { "fr-FR": "ltr", "ar-MA": "rtl" },
};
export const SETTINGS: Routes = {
  "GET /api/git-connections": { status: 200, body: [CONNECTION] },
  "GET /api/security-services": { status: 200, body: [] },
  // Posées dans le jeu COMMUN, et non dans les seuls tests qui les regardent : un écran
  // qui interroge une route absente des doublures n'échoue pas, il affiche son chemin
  // d'erreur, et les tests restent verts en l'exerçant en silence (LESSONS.md).
  "GET /api/cultures": { status: 200, body: CATALOGUE },
  "GET /api/workspaces/retrait/cultures": { status: 200, body: WORKSPACE_CULTURES },
};

/**
 * La personne connectée a la main sur la branche enfant « edition » (story 9def0adc) :
 * sans elle, les écrans n'offrent aucun bouton de modification.
 */
export const HELD: Routes = {
  "GET /api/workspaces/retrait/holds": {
    status: 200,
    body: [{ slug: "edition", holder: "Gael (gael)", mine: true, taken_at: "2026-10-23T08:00:00Z" }],
  },
};

/** L'écran avec la sélection que lui tient le portail, ici tenue localement. */
function Workspaces({ initial }: { initial: WorkspaceSelection }) {
  const [selection, setSelection] = useState<WorkspaceSelection>(initial);
  return <WorkspacesScreen selection={selection} onSelect={setSelection} />;
}

export function renderWorkspaces(initial: WorkspaceSelection = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Workspaces initial={initial} />
    </QueryClientProvider>,
  );
}

export function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
