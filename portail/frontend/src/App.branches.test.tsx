import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { ADMIN, BRANCHES, openMenu, renderApp } from "./appTestHarness";
import { mockApi } from "@miles/socle-web/testing";
import { BARE, CONFIGURED } from "./workspaces/workspaceFixtures";

/**
 * La BRANCHE VUE : ce qu'elle nomme dans le menu, et ce qu'elle ouvre.
 *
 * Réparti par NATURE le 3 novembre 2026 (enabler `82ec7d76`). Un workspace porte le nom
 * de la branche regardée, et changer de branche renomme ce que le menu annonce : c'est la
 * garde qui tient cette équivalence, et elle se lit mieux seule.
 */
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App, selon la branche vue", () => {
  it("names each workspace after the branch viewed, and opens that branch's views", async () => {
    const calls = mockApi({
      ...ADMIN,
      "GET /api/workspaces": {
        status: 200,
        body: [
          { ...CONFIGURED, work_branch: "back/retrait/atelier" },
          { ...BARE, id: "caisse", name: "Caisse" },
        ],
      },
      "GET /api/branch-views": { status: 200, body: { retrait: "essai" } },
      "GET /api/workspaces/retrait/branches": { status: 200, body: BRANCHES },
      "GET /api/workspaces/retrait/data-models?branch=essai": { status: 200, body: [] },
      "GET /api/workspaces/retrait/contracts?branch=essai": { status: 200, body: [] },
      "GET /api/workspaces/retrait/storages?branch=essai": { status: 200, body: [] },
      "GET /api/workspaces/retrait/versions?branch=essai": { status: 200, body: [] },
      // Simulée, et avec du CONTENU : sans elle la carte du graphe s'afficherait
      // quand même — sur son chemin d'erreur — et l'assertion ne distinguerait pas
      // « le graphe est là » de « le graphe n'a pas pu être lu » (LESSONS.md).
      "GET /api/workspaces/retrait/branches/graph": {
        status: 200,
        body: [
          {
            sha: "aaaaaaa1111",
            parents: [],
            author: "Gaël",
            written_at: "2026-10-24T10:00:00Z",
            subject: "premier commit",
            refs: [],
          },
        ],
      },
    });
    renderApp();
    const nav = await screen.findByRole("navigation");
    await openMenu("Workspaces");
    const retrait = await within(nav).findByRole("button", { name: "Retrait de colis (essai)" });
    // Replié par défaut : avec beaucoup de workspaces, tout déplier noierait le menu.
    expect(retrait).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(retrait);
    // Les branches ne sont pas listées : seules les vues de la branche regardée.
    expect(within(nav).queryByRole("button", { name: "atelier" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("button", { name: "Settings" })).not.toBeInTheDocument();
    // UNE SEULE entrée pour la branche depuis la fusion du 01/11/2026 (Gael) : ses
    // versions et le graphe de toutes les branches sont le même écran, et l'ancienne
    // entrée « Branches » n'existe plus. Un écran qu'on ne peut pas ouvrir n'existe pas,
    // et le menu a sa PROPRE liste de vues (relevé par Gael le 24/10/2026) : on l'OUVRE
    // donc, et on vérifie que les DEUX contenus y sont — une entrée qui n'en servirait
    // qu'un aurait fondu les menus sans fondre les écrans.
    expect(within(nav).queryByRole("button", { name: "Branches" })).not.toBeInTheDocument();
    // Et AUCUNE entrée n'affiche une clef de traduction brute. La ligne au-dessus ne
    // suffit pas : remettre « branchGraph » dans la liste des vues la laisse verte,
    // puisque le libellé a disparu avec la fusion et que le bouton montre alors sa clef.
    // Mesuré en sabotant le 01/11/2026. Cette garde-ci attrape toute la famille — une
    // vue ajoutée sans son libellé dans les deux langues.
    const clef = /^[a-z][a-zA-Z]*(\.[a-zA-Z_]+)+$/;
    expect(
      within(nav)
        .getAllByRole("button")
        .map((b) => b.textContent ?? "")
        .filter((libelle) => clef.test(libelle)),
    ).toEqual([]);
    fireEvent.click(within(nav).getByRole("button", { name: "Branches and versions" }));
    expect(
      await screen.findByRole("region", { name: "Versions of the work branch" }),
    ).toBeInTheDocument();
    const graphe = await screen.findByRole("region", { name: "Branches" });
    expect(within(graphe).getByText("premier commit")).toBeInTheDocument();
    // Même garde pour « Storages » (24/10/2026) : la vue est déclarée dans la liste du
    // menu, pas seulement dans le routage — sans quoi l'écran serait inatteignable.
    fireEvent.click(within(nav).getByRole("button", { name: "Storages" }));
    expect(
      await screen.findByRole("heading", { name: "Storages — Retrait de colis" }),
    ).toBeInTheDocument();
    // « Data models » PORTE des entrées : depuis le 30/10/2026 son bouton replie le
    // groupe, et l'écran s'ouvre par l'entrée dédiée — un clic ne fait qu'une chose.
    await openMenu("Data models");
    fireEvent.click(within(nav).getByRole("button", { name: "All models" }));

    expect(
      await screen.findByRole("heading", { name: "Data models — Retrait de colis" }),
    ).toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: "All models" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(calls.some((c) => c.key.includes("branch=atelier"))).toBe(false);
    // Sans branche de travail, rien à déplier : le nom ouvre le paramétrage du workspace.
    const caisse = within(nav).getByRole("button", { name: "Caisse" });
    expect(caisse).not.toHaveAttribute("aria-expanded");
    fireEvent.click(caisse);
    expect(await screen.findByRole("heading", { name: /Caisse/ })).toBeInTheDocument();
    expect(caisse).toHaveAttribute("aria-current", "page");
  });

  it("switches the branch viewed from All workspaces, which renames the workspace in the menu", async () => {
    const calls = mockApi({
      ...ADMIN,
      "GET /api/workspaces": { status: 200, body: [{ ...CONFIGURED, work_branch: "back/retrait/atelier" }] },
      "GET /api/branch-views": [
        { status: 200, body: {} },
        { status: 200, body: { retrait: "essai" } },
      ],
      "GET /api/workspaces/retrait/branches": { status: 200, body: BRANCHES },
      "PUT /api/workspaces/retrait/branches/view": { status: 200, body: BRANCHES[1] },
    });
    renderApp();
    const nav = await screen.findByRole("navigation");
    // Le menu reste REPLIÉ : ce test parle du libellé que le menu porte, pas de son
    // ouverture, et le lire par le texte ne dépend donc pas du moment où on déplie.
    // Lu par `findByRole` après un dépliage, l'attente laissait la doublure séquentielle
    // servir sa SECONDE réponse, et le test mesurait l'état d'après plutôt que celui
    // d'avant — il dépendait du temps, ce que mon dépliage a seulement révélé.
    const menuPorte = async (libelle: string) =>
      await waitFor(() =>
        expect(
          [...nav.querySelectorAll("button")].map((b) => b.textContent),
        ).toContain(libelle),
      );
    // Sans choix enregistré, c'est la branche de base qu'on regarde.
    await menuPorte("Retrait de colis (atelier)");
    const picker = await screen.findByLabelText("Branch viewed");
    await within(picker).findByRole("option", { name: "essai" });

    fireEvent.change(picker, { target: { value: "essai" } });

    await menuPorte("Retrait de colis (essai)");
    expect(calls.find((c) => c.key === "PUT /api/workspaces/retrait/branches/view")?.body).toEqual({
      branch: "essai",
    });
  });

  it("lists the declared contracts under the branch viewed, and opens one from the menu", async () => {
    const declared = { slug: "suivi", label: "Suivi des demandes", sens: "externe", versions: [] };
    mockApi({
      ...ADMIN,
      "GET /api/workspaces": { status: 200, body: [{ ...CONFIGURED, work_branch: "back/retrait/atelier" }] },
      "GET /api/branch-views": { status: 200, body: {} },
      "GET /api/workspaces/retrait/branches": { status: 200, body: BRANCHES },
      "GET /api/workspaces/retrait/contracts?branch=atelier": { status: 200, body: [declared] },
      "GET /api/workspaces/retrait/contracts/suivi?branch=atelier": { status: 200, body: declared },
    });
    renderApp();
    const nav = await screen.findByRole("navigation");
    await openMenu("Workspaces");
    fireEvent.click(await within(nav).findByRole("button", { name: "Retrait de colis (atelier)" }));

    await openMenu("Contracts");
    const contract = await within(nav).findByRole("button", { name: "Suivi des demandes" });
    fireEvent.click(contract);

    expect(await screen.findByRole("heading", { name: "Suivi des demandes" })).toBeInTheDocument();
    expect(contract).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("button", { name: "Contracts" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});
