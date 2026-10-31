import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import type { TradsCoverage } from "../api/tradsCoverage";
import { type Routes, mockApi } from "@miles/socle-web/testing";
import { WorkspaceViews } from "../layout/WorkspaceViews";
import { CONFIGURED, HELD, SETTINGS, renderWorkspaces } from "./workspaceFixtures";

// Couverture des traductions (story 82e60880) : l'installation, le contexte, et le
// raccourci vers les clés qui manquent.
const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/trads/coverage?branch=edition";
const KEYS = "/api/workspaces/retrait/trads/accueil/keys?branch=edition";
// La culture par défaut est `fr-FR` et NON `en-US` : c'est ce qui rend le jeu d'essai
// discriminant sur le critère 6. Avec `en-US` par défaut, un écran qui coderait `en-US`
// en dur resterait vert.
const COVERAGE: TradsCoverage = {
  branch: "back/retrait/edition",
  default: "fr-FR",
  keys: 10,
  threshold: 50,
  cultures: [
    {
      culture: "fr-FR",
      translated: 10,
      missing: 0,
      is_default: true,
      low: false,
      inconsistent: false,
    },
    {
      culture: "ar-MA",
      translated: 2,
      missing: 8,
      is_default: false,
      low: true,
      inconsistent: false,
    },
  ],
  contexts: [
    {
      name: "accueil",
      label: "Écrans d'accueil",
      keys: 10,
      translated: { "fr-FR": 10, "ar-MA": 2 },
      obsolete: {},
    },
    { name: "vide", label: "Encore vide", keys: 0, translated: {}, obsolete: {} },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function routes(coverage: TradsCoverage = COVERAGE, extra: Routes = {}) {
  return mockApi({
    ...HELD,
    ...SETTINGS,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    [`GET ${ROUTE}`]: { status: 200, body: coverage },
    ...extra,
  });
}

async function open() {
  renderWorkspaces({ id: "retrait", view: "tradsCoverage", branch: "edition" });
  await screen.findByRole("heading", { name: "Translation coverage" });
  // Attendre la COUVERTURE et non le titre : le titre s'affiche avant la lecture du
  // dépôt, et les assertions porteraient sur l'écran encore en attente.
  return screen.findByText(/^Branch read:/);
}

describe("TradsCoverageScreen", () => {
  it("gives the coverage of every active culture, the branch it read and the contexts", async () => {
    routes();
    await open();

    // Critère 1 : traduites sur le total, pour chaque culture active. Lu DANS la liste
    // « par culture » : les mêmes comptes figurent par contexte, et une recherche sur
    // tout l'écran ne dirait pas lequel des deux niveaux on mesure.
    const cultures = screen.getByRole("list", { name: "By culture" });
    expect(within(cultures).getByText("10 / 10")).toBeInTheDocument();
    expect(within(cultures).getByText("2 / 10")).toBeInTheDocument();
    expect(within(cultures).getByText("100%")).toBeInTheDocument();
    expect(within(cultures).getByText("20%")).toBeInTheDocument();
    // Critère 11 : la branche RÉELLEMENT lue, telle que le serveur la nomme.
    expect(screen.getByText("Branch read: back/retrait/edition")).toBeInTheDocument();
    expect(screen.getByText("10 key(s) on this branch")).toBeInTheDocument();
    // Critère 2 : contexte par contexte, et on repère celui qui est en retard.
    const contexts = screen.getByRole("list", { name: "By context" });
    const accueil = within(contexts).getByText("Écrans d'accueil").closest("li") as HTMLElement;
    expect(within(accueil).getByText("2 / 10")).toBeInTheDocument();
    expect(within(contexts).getByText("Encore vide")).toBeInTheDocument();
  });

  it("flags the barely translated culture with the threshold it applied", async () => {
    routes();
    await open();

    expect(screen.getByText("Barely translated (under 50%)")).toBeInTheDocument();
  });

  it("never presents the workspace default culture as translation work", async () => {
    // Très en dessous du seuil, et pourtant la culture par défaut : le serveur dit
    // `low: false` et `inconsistent: true`, et l'écran doit le dire comme une
    // incohérence du DÉPÔT (critère 6).
    const broken: TradsCoverage = {
      ...COVERAGE,
      cultures: [
        {
          culture: "fr-FR",
          translated: 3,
          missing: 7,
          is_default: true,
          low: false,
          inconsistent: true,
        },
      ],
      contexts: [COVERAGE.contexts[0] as TradsCoverage["contexts"][number]],
    };
    routes(broken);
    await open();

    expect(screen.getByText("Default culture")).toBeInTheDocument();
    expect(screen.queryByText(/Barely translated/)).toBeNull();
    expect(
      screen.getByText(/7 key\(s\) with no value in the default culture/),
    ).toBeInTheDocument();
    expect(screen.getByText(/repository inconsistency, not translation work/)).toBeInTheDocument();
  });

  it("says an empty context is empty rather than covered", async () => {
    routes();
    await open();

    const row = screen.getByText("Encore vide").closest("li") as HTMLElement;
    expect(within(row).getByText("Empty")).toBeInTheDocument();
    // Ni « 100% » ni « 0% » sur cette ligne : zéro sur zéro n'est pas un taux.
    expect(within(row).queryByText(/%$/)).toBeNull();
  });

  it("is reached from a Translations group that also holds the contexts", () => {
    const onSelect = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <WorkspaceViews
          workspaceId="retrait"
          branch="edition"
          open={false}
          active
          selection={null}
          onSelect={onSelect}
        />
      </QueryClientProvider>,
    );

    // « Translations » porte deux entrées depuis cette story : gérer les contextes et
    // lire la couverture sont deux gestes, et le menu est replié au chargement.
    fireEvent.click(screen.getByRole("button", { name: "Translations" }));
    fireEvent.click(screen.getByRole("button", { name: "Coverage" }));
    fireEvent.click(screen.getByRole("button", { name: "Contexts" }));

    expect(onSelect.mock.calls).toEqual([
      [{ id: "retrait", view: "tradsCoverage", branch: "edition" }],
      [{ id: "retrait", view: "trads", branch: "edition" }],
    ]);
  });

  it("opens the keys of a context already filtered on the culture that misses them", async () => {
    const calls = routes(COVERAGE, {
      [`GET ${KEYS}&search=&offset=0&limit=50&untranslated=ar-MA`]: {
        status: 200,
        body: { keys: [], total: 0 },
      },
      "GET /api/workspaces/retrait/cultures": {
        status: 200,
        body: { default: "fr-FR", additional: ["ar-MA"], directions: {} },
      },
    });
    await open();

    // Huit clés sans valeur en `ar-MA` dans ce contexte : c'est le chemin vers elles.
    fireEvent.click(screen.getByRole("button", { name: "8 to translate" }));

    expect(await screen.findByRole("heading", { name: /accueil/ })).toBeInTheDocument();
    await vi.waitFor(() =>
      expect(
        calls.some((c) => c.key.includes("untranslated=ar-MA") && c.key.startsWith("GET ")),
      ).toBe(true),
    );
  });
});
