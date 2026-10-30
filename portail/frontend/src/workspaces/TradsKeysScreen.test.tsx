import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { marksIn } from "../api/tradsKeys";
import { type Routes, mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, SETTINGS, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const CULTURES = "/api/workspaces/retrait/cultures";
const KEYS = "/api/workspaces/retrait/trads/accueil/keys?branch=edition";
// ar-MA s'écrit de droite à gauche : c'est la culture qui rend les critères mesurables.
const WS_CULTURES = {
  default: "fr-FR",
  additional: ["ar-MA"],
  directions: { "fr-FR": "ltr", "ar-MA": "rtl" },
};
const TITRE = {
  slug: "titre",
  values: { "fr-FR": "Bonjour", "ar-MA": "مرحبا" },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

function routes(page: object, extra: Routes = {}) {
  return mockApi({
    ...HELD,
    ...SETTINGS,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    [`GET ${CULTURES}`]: { status: 200, body: WS_CULTURES },
    [`GET ${KEYS}&search=&offset=0&limit=50`]: page as Routes[string],
    ...extra,
  });
}

async function openKeys() {
  renderWorkspaces({
    id: "retrait",
    view: "trads",
    branch: "edition",
    tradsContext: "accueil",
  });
  await screen.findByRole("heading", { name: "Translations — accueil" });
}

function fieldOf(culture: string): HTMLTextAreaElement {
  const field = document.querySelector(`textarea[lang="${culture}"]`);
  return field as HTMLTextAreaElement;
}

describe("marksIn", () => {
  it("names the invisible direction marks a value carries", () => {
    expect(marksIn("Nom‏suite")).toEqual(["RLM"]);
    expect(marksIn("a‎b؜c")).toEqual(["LRM", "ALM"]);
    expect(marksIn("rien d'invisible")).toEqual([]);
  });
});

describe("TradsKeysScreen", () => {
  it("shows one value per workspace culture, the default one first", async () => {
    routes({ status: 200, body: { keys: [TITRE], total: 1 } });
    await openKeys();

    await screen.findByText("Bonjour");
    const row = screen.getByText("titre").closest("li") as HTMLElement;
    const codes = [...row.querySelectorAll(".caption")].map((e) => e.textContent);
    expect(codes).toEqual(["fr-FR", "ar-MA"]);
  });

  it("opens the edition from the whole row, and keeps the other actions reachable", async () => {
    routes({ status: 200, body: { keys: [TITRE], total: 1 } });
    await openKeys();

    const row = (await screen.findByText("titre")).closest("li") as HTMLElement;
    // Le bouton du slug couvre la ligne (`row-open::after { inset: 0 }`) : il n'y a plus
    // de bouton « Modifier », c'est la ligne qui ouvre.
    expect(within(row).queryByText("Edit")).not.toBeInTheDocument();
    expect(row.className).toContain("row-openable");
    // Et les actions repassent AU-DESSUS de ce calque. jsdom ne calcule aucun rectangle :
    // ce test prouve que la classe est là, pas que le clic atteint le bouton. La mesure
    // qui mord est celle d'un vrai navigateur (LESSONS.md, mise en page).
    expect(within(row).getByText("Rename").closest(".actions")?.className).toContain(
      "row-actions",
    );
  });

  // --- Critères 7, 8, 9 : la langue et le sens viennent de la CULTURE ---

  it("declares the language and the direction on each field, not on the page", async () => {
    routes({ status: 200, body: { keys: [TITRE], total: 1 } });
    await openKeys();
    fireEvent.click(await screen.findByRole("button", { name: "titre" }));

    expect(fieldOf("fr-FR")).toHaveAttribute("dir", "ltr");
    expect(fieldOf("ar-MA")).toHaveAttribute("dir", "rtl");
    // La page, elle, ne bascule pas : c'est le critère 8.
    expect(document.documentElement).not.toHaveAttribute("dir", "rtl");
    expect(document.body).not.toHaveAttribute("dir", "rtl");
  });

  it("never uses dir=auto, which would guess the direction from the content", async () => {
    routes({ status: 200, body: { keys: [TITRE], total: 1 } });
    await openKeys();
    fireEvent.click(await screen.findByRole("button", { name: "titre" }));

    // `dir="auto"` disposerait de gauche à droite une valeur arabe commençant par un nom
    // de marque latin : l'erreur n'apparaîtrait que sur certaines valeurs, donc tard.
    expect(document.querySelectorAll('[dir="auto"]')).toHaveLength(0);
  });

  it("keeps the direction from the culture on a value starting with latin or a digit", async () => {
    // C'est le critère qui prouve que le sens vient de la culture et non du contenu.
    const latinFirst = { slug: "marque", values: { "fr-FR": "Acme", "ar-MA": "Acme شركة" } };
    routes({ status: 200, body: { keys: [latinFirst], total: 1 } });
    await openKeys();

    const cell = (await screen.findByText("Acme شركة")) as HTMLElement;
    expect(cell).toHaveAttribute("dir", "rtl");
    expect(cell).toHaveAttribute("lang", "ar-MA");
  });

  it("isolates each displayed value from its neighbours", async () => {
    routes({ status: 200, body: { keys: [TITRE], total: 1 } });
    await openKeys();

    // La classe porte `unicode-bidi: isolate` : sans elle, la ponctuation de bord d'une
    // valeur droite-à-gauche migre de l'autre côté dans un tableau gauche-à-droite.
    const cell = (await screen.findByText("مرحبا")) as HTMLElement;
    expect(cell.className).toContain("value-cell");
  });

  it("marks the right-to-left columns and the required one", async () => {
    routes({ status: 200, body: { keys: [TITRE], total: 1 } });
    await openKeys();
    fireEvent.click(await screen.findByRole("button", { name: "titre" }));

    const arabic = fieldOf("ar-MA").closest("label") as HTMLElement;
    expect(within(arabic).getByText("(right to left)")).toBeInTheDocument();
    const french = fieldOf("fr-FR").closest("label") as HTMLElement;
    expect(within(french).getByText("(required)")).toBeInTheDocument();
  });

  it("names the invisible marks a value carries", async () => {
    const withMark = { slug: "marque", values: { "fr-FR": "Bonjour", "ar-MA": "شركة‏ Acme" } };
    routes({ status: 200, body: { keys: [withMark], total: 1 } });
    await openKeys();
    fireEvent.click(await screen.findByRole("button", { name: "marque" }));

    expect(await screen.findByText(/invisible direction marks: RLM/)).toBeInTheDocument();
  });

  // --- Critère 4 : seule la culture touchée part dans le corps ---

  it("sends only the cultures whose value actually changed", async () => {
    const calls = routes(
      { status: 200, body: { keys: [TITRE], total: 1 } },
      { [`PUT /api/workspaces/retrait/trads/accueil/keys/titre?branch=edition`]: {
          status: 200,
          body: { slug: "titre" },
        } },
    );
    await openKeys();
    fireEvent.click(await screen.findByRole("button", { name: "titre" }));

    fireEvent.change(fieldOf("ar-MA"), { target: { value: "أهلا" } });
    fireEvent.click(screen.getByText("Save"));

    await vi.waitFor(() => {
      const call = calls.find((c) => c.key.startsWith("PUT /api/workspaces/retrait/trads"));
      expect(call?.body).toEqual({ values: { "ar-MA": "أهلا" } });
    });
  });

  it("sends null for a value that was emptied, so its line leaves the file", async () => {
    const calls = routes(
      { status: 200, body: { keys: [TITRE], total: 1 } },
      { [`PUT /api/workspaces/retrait/trads/accueil/keys/titre?branch=edition`]: {
          status: 200,
          body: { slug: "titre" },
        } },
    );
    await openKeys();
    fireEvent.click(await screen.findByRole("button", { name: "titre" }));

    fireEvent.change(fieldOf("ar-MA"), { target: { value: "" } });
    fireEvent.click(screen.getByText("Save"));

    await vi.waitFor(() => {
      const call = calls.find((c) => c.key.startsWith("PUT /api/workspaces/retrait/trads"));
      expect(call?.body).toEqual({ values: { "ar-MA": null } });
    });
  });

  it("sends nothing when no value changed", async () => {
    const calls = routes(
      { status: 200, body: { keys: [TITRE], total: 1 } },
      { [`PUT /api/workspaces/retrait/trads/accueil/keys/titre?branch=edition`]: {
          status: 200,
          body: { slug: "titre" },
        } },
    );
    await openKeys();
    fireEvent.click(await screen.findByRole("button", { name: "titre" }));

    fireEvent.click(screen.getByText("Save"));

    await vi.waitFor(() => {
      const call = calls.find((c) => c.key.startsWith("PUT /api/workspaces/retrait/trads"));
      expect(call?.body).toEqual({ values: {} });
    });
  });

  // --- Ajout, renommage, suppression ---

  it("adds a key with its value in the default culture", async () => {
    const calls = routes(
      { status: 200, body: { keys: [], total: 0 } },
      { [`POST ${KEYS}`]: { status: 201, body: { slug: "adieu" } } },
    );
    await openKeys();
    fireEvent.click(await screen.findByText("Add a key"));

    fill("Key identifier", "adieu");
    fireEvent.change(fieldOf("fr-FR"), { target: { value: "Au revoir" } });
    fireEvent.click(screen.getByText("Add the key"));

    await vi.waitFor(() => {
      const call = calls.find((c) => c.key === `POST ${KEYS}`);
      // ar-MA est resté vide : il n'entre pas dans le corps, et son fichier reste intact.
      expect(call?.body).toEqual({ slug: "adieu", values: { "fr-FR": "Au revoir" } });
    });
  });

  it("does not even submit while the default culture's value is empty", async () => {
    // La garde est NATIVE : le champ de la culture par défaut est `required`, donc le
    // formulaire ne part pas. Le serveur refuse aussi, mais l'écran n'y arrive jamais —
    // ce test mesure donc ce qui se produit vraiment, pas le refus qu'on espérait voir.
    const calls = routes(
      { status: 200, body: { keys: [], total: 0 } },
      { [`POST ${KEYS}`]: { status: 201, body: { slug: "adieu" } } },
    );
    await openKeys();
    fireEvent.click(await screen.findByText("Add a key"));
    fill("Key identifier", "adieu");

    expect(fieldOf("fr-FR")).toBeRequired();
    expect(fieldOf("ar-MA")).not.toBeRequired();
    fireEvent.click(screen.getByText("Add the key"));

    await vi.waitFor(() => expect(calls.some((c) => c.key === `POST ${KEYS}`)).toBe(false));
  });

  it("names the refused direction characters, which are invisible", async () => {
    routes(
      { status: 200, body: { keys: [], total: 0 } },
      { [`POST ${KEYS}`]: {
          status: 422,
          body: {
            detail: { code: "direction_forcee", found: ["U+202E RIGHT-TO-LEFT OVERRIDE"] },
          },
        } },
    );
    await openKeys();
    fireEvent.click(await screen.findByText("Add a key"));
    fill("Key identifier", "titre");
    fireEvent.change(fieldOf("fr-FR"), { target: { value: "Bonjour" } });

    fireEvent.click(screen.getByText("Add the key"));

    expect(await screen.findByRole("alert")).toHaveTextContent("U+202E RIGHT-TO-LEFT OVERRIDE");
  });

  it("warns before renaming, because nothing can tell what references a key", async () => {
    const calls = routes(
      { status: 200, body: { keys: [TITRE], total: 1 } },
      { [`POST /api/workspaces/retrait/trads/accueil/keys/titre/rename?branch=edition`]: {
          status: 200,
          body: { slug: "accroche" },
        } },
    );
    await openKeys();

    fireEvent.click(await screen.findByText("Rename"));

    expect(screen.getByText(/may break references/)).toBeInTheDocument();
    fill("Key identifier", "accroche");
    fireEvent.click(screen.getByText("Rename the key"));
    await vi.waitFor(() => {
      const call = calls.find((c) => c.key.includes("/rename"));
      expect(call?.body).toEqual({ new_slug: "accroche" });
    });
  });

  it("warns before deleting, and says how many values disappear", async () => {
    routes({ status: 200, body: { keys: [TITRE], total: 1 } });
    await openKeys();

    fireEvent.click(await screen.findByText("Delete"));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/may break references/);
    expect(dialog).toHaveTextContent("2 value(s) will disappear");
  });

  // --- Critère 18 : filtre, pagination ---

  it("asks only the untranslated keys of a culture", async () => {
    const calls = routes(
      { status: 200, body: { keys: [TITRE], total: 1 } },
      { [`GET ${KEYS}&search=&offset=0&limit=50&untranslated=ar-MA`]: {
          status: 200,
          body: { keys: [], total: 0 },
        } },
    );
    await openKeys();
    await screen.findByText("Bonjour");

    fireEvent.change(screen.getByLabelText("Untranslated in"), { target: { value: "ar-MA" } });

    expect(await screen.findByText("No key matches this filter.")).toBeInTheDocument();
    expect(calls.some((c) => c.key.includes("untranslated=ar-MA"))).toBe(true);
  });

  it("pages through a context that holds more keys than a page", async () => {
    const many = Array.from({ length: 50 }, (_, i) => ({
      slug: `cle-${i}`,
      values: { "fr-FR": `V${i}` },
    }));
    const calls = routes(
      { status: 200, body: { keys: many, total: 120 } },
      { [`GET ${KEYS}&search=&offset=50&limit=50`]: {
          status: 200,
          body: { keys: [TITRE], total: 120 },
        } },
    );
    await openKeys();
    await screen.findByText("1–50 of 120");

    fireEvent.click(screen.getByText("Next page"));

    expect(await screen.findByText("51–100 of 120")).toBeInTheDocument();
    expect(calls.some((c) => c.key.includes("offset=50"))).toBe(true);
  });

  // --- Critère 19 : l'édition concurrente ---

  it("says nothing was lost when the branch moved during a save", async () => {
    routes(
      { status: 200, body: { keys: [TITRE], total: 1 } },
      { [`PUT /api/workspaces/retrait/trads/accueil/keys/titre?branch=edition`]: {
          status: 409,
          body: { detail: { code: "branche_a_bouge" } },
        } },
    );
    await openKeys();
    fireEvent.click(await screen.findByRole("button", { name: "titre" }));
    fireEvent.change(fieldOf("fr-FR"), { target: { value: "Salut" } });

    fireEvent.click(screen.getByText("Save"));

    expect(await screen.findByRole("alert")).toHaveTextContent("no value was lost");
  });

  // --- Critère 20 : les droits ---

  it("offers no editing on a branch nobody holds", async () => {
    mockApi({
      ...SETTINGS,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      "GET /api/workspaces/retrait/holds": { status: 200, body: [] },
      [`GET ${CULTURES}`]: { status: 200, body: WS_CULTURES },
      [`GET ${KEYS}&search=&offset=0&limit=50`]: {
        status: 200,
        body: { keys: [TITRE], total: 1 },
      },
    });
    await openKeys();
    await screen.findByText("Bonjour");

    expect(screen.queryByText("Add a key")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "titre" })).not.toBeInTheDocument();
    expect(screen.queryByText("Rename")).not.toBeInTheDocument();
    expect(screen.queryByText("Delete")).not.toBeInTheDocument();
  });

  it("names the unreadable file rather than failing silently", async () => {
    routes({
      status: 422,
      body: { detail: { code: "trads_illisible", path: "trads/accueil/fr-FR.yaml" } },
    });
    await openKeys();

    expect(await screen.findByRole("alert")).toHaveTextContent("trads/accueil/fr-FR.yaml");
  });
});
