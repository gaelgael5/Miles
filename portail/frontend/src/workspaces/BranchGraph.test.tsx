import { screen } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "../test/mockApi";
import { CONFIGURED, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/root" };
const GRAPH = "/api/workspaces/retrait/branches/graph?limit=100";

function commit(sha: string, parents: string[], subject: string, refs: string[] = []) {
  return { sha, parents, author: "Gaël", written_at: "2026-10-24T10:00:00Z", subject, refs };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function open(body: unknown, status = 200) {
  mockApi({
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    [`GET ${GRAPH}`]: { status, body },
  });
  renderWorkspaces({ id: "retrait", view: "branchGraph", branch: "root" });
}

describe("branch graph (24/10/2026)", () => {
  it("shows each commit with its branch and short sha", async () => {
    open([
      commit("aaaaaaa1111", ["bbbbbbb2222"], "sur essai", ["back/retrait/essai"]),
      commit("bbbbbbb2222", [], "racine", ["back/retrait/root"]),
    ]);

    expect(await screen.findByText("sur essai")).toBeInTheDocument();
    // Le préfixe du workspace est le même partout : on n'affiche que le nom court.
    expect(screen.getByText("essai")).toBeInTheDocument();
    expect(screen.getByText("root")).toBeInTheDocument();
    expect(screen.getByText(/aaaaaaa/)).toBeInTheDocument();
  });

  it("draws one rail per commit, and links a child to its parent", async () => {
    open([
      commit("aaaaaaa1111", ["bbbbbbb2222"], "enfant"),
      commit("bbbbbbb2222", [], "parent"),
    ]);
    await screen.findByText("enfant");

    // Deux pastilles, et un trait de l'enfant vers son parent.
    expect(document.querySelectorAll(".graph-dot")).toHaveLength(2);
    expect(document.querySelectorAll(".graph-edge")).toHaveLength(1);
  });

  it("says plainly when the workspace has no commit yet", async () => {
    open([]);

    expect(await screen.findByText(/no branch yet/)).toBeInTheDocument();
    expect(document.querySelectorAll(".graph-dot")).toHaveLength(0);
  });

  it("says when the repository did not answer, instead of showing an empty graph", async () => {
    open({ detail: "acces_depot" }, 502);

    expect(await screen.findByText(/did not answer/)).toBeInTheDocument();
  });
});
