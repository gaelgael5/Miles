import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";

import type { Routes } from "../test/mockApi";
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
export const SETTINGS: Routes = {
  "GET /api/git-connections": { status: 200, body: [CONNECTION] },
  "GET /api/security-services": { status: 200, body: [] },
};

export function renderWorkspaces() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WorkspacesScreen />
    </QueryClientProvider>,
  );
}

export function fill(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
