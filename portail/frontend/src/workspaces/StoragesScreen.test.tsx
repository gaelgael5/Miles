import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/storages";
const Q = "?branch=edition";
const STORAGE = {
  name: "sites",
  label: "Sites",
  model: "shared/site",
  keys: ["$.code"],
  indexes: [{ name: "par-ville", columns: ["$.adresse.ville"] }],
  expiries: [],
};
const MODELS = {
  [`GET /api/workspaces/retrait/data-models${Q}`]: {
    status: 200,
    body: [{ scope: "shared", name: "site", path: "data-models/shared/site.yaml" }],
  },
  // L'arbre se coche : il vient de la route des chemins, celle de l'intellisense JSLT.
  [`GET /api/workspaces/retrait/data-models/shared/site/paths${Q}`]: {
    status: 200,
    body: {
      paths: [
        { path: "$.code", type: "string", description: "" },
        { path: "$.adresse", type: "object", description: "" },
        { path: "$.adresse.ville", type: "string", description: "Ville" },
        { path: "$.adresse.pays", type: "string", description: "" },
        { path: "$.rang", type: "integer", description: "" },
        { path: "$.fin", type: "string", description: "", format: "date-time" },
        { path: "$.enseignes", type: "array", description: "" },
        { path: "$.enseignes[0]", type: "string", description: "" },
      ],
    },
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StoragesScreen (24/10/2026)", () => {
  it("declares a storage with its model, functional key and indexable properties", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`POST ${ROUTE}${Q}`]: { status: 201, body: { ...STORAGE, rewrite_announced: false } },
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: STORAGE },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition" });
    expect(await screen.findByText("No storage on this branch.")).toBeInTheDocument();

    fireEvent.click(screen.getByText("New storage"));
    // Le libellé est libre ; l'identifiant s'en déduit — « Sites » ne se fait pas refuser
    // sur sa majuscule (Gael, 24/10/2026).
    fill("Label", "Sites");
    expect(screen.getByLabelText("Name")).toHaveValue("sites");
    await screen.findByRole("option", { name: "shared/site" });
    fill("Object model", "shared/site");

    // L'arbre n'est pas affiché : c'est le champ qui l'ouvre (Gael, 24/10/2026).
    expect(screen.queryByRole("list", { name: "Functional key" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Functional key" }));
    const keyTree = await screen.findByRole("list", { name: "Functional key" });
    fireEvent.click(within(keyTree).getByRole("checkbox", { name: /code/ }));
    // Cocher ne referme pas : la sélection est multiple.
    expect(screen.getByRole("list", { name: "Functional key" })).toBeInTheDocument();
    fireEvent.click(screen.getByText("Done"));

    // « l'utilisateur ajoute un index et après il choisit les colonnes » (Gael).
    fireEvent.click(screen.getByText("Add an index"));
    expect(screen.getByLabelText("Name of index 1")).toHaveValue("index-1");
    fireEvent.change(screen.getByLabelText("Name of index 1"), {
      target: { value: "par-ville" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Columns of index par-ville" }));
    const indexTree = await screen.findByRole("list", { name: "Columns of index par-ville" });
    fireEvent.click(within(indexTree).getByRole("checkbox", { name: /ville/ }));
    fireEvent.click(screen.getByText("Declare the storage"));

    expect(await screen.findByText("storages/sites.yaml")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${ROUTE}${Q}`)?.body).toEqual(STORAGE);
  });

  it("shows every refusal with the path it concerns", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`POST ${ROUTE}${Q}`]: {
        status: 422,
        body: {
          detail: {
            code: "storage_invalide",
            problems: [
              { path: "index[0].colonnes[0]", code: "tableau_interdit", detail: "$.enseignes" },
              { path: "cle[0]", code: "propriete_inconnue", detail: "$.rien" },
            ],
          },
        },
      },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition" });
    fireEvent.click(await screen.findByText("New storage"));
    fill("Label", "Sites");
    fireEvent.submit(screen.getByRole("form", { name: "Declare the storage" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("index[0].colonnes[0]")).toBeInTheDocument();
    expect(alert).toHaveTextContent("“$.enseignes” designates an array");
    expect(alert).toHaveTextContent("“$.rien” designates nothing in the storage model.");
  });

  it("lists a storage with its model and its key", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}${Q}`]: {
        status: 200,
        body: [{ name: "sites", label: "Sites", model: "shared/site", keys: ["$.code"] }],
      },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition" });

    expect(await screen.findByText("storages/sites.yaml")).toBeInTheDocument();
    expect(screen.getByText("Sites")).toBeInTheDocument();
    expect(screen.getByText("shared/site")).toBeInTheDocument();
    expect(screen.getByText("$.code")).toBeInTheDocument();
  });

  it("opens a storage from its whole row, with no Open button", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}${Q}`]: {
        status: 200,
        body: [{ name: "sites", label: "Sites", model: "shared/site", keys: ["$.code"] }],
      },
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: STORAGE },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition" });

    expect(await screen.findByText("storages/sites.yaml")).toBeInTheDocument();
    expect(screen.queryByText("Open")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sites" }));

    expect(await screen.findByLabelText("Object model")).toBeInTheDocument();
  });
});

describe("StorageScreen (24/10/2026)", () => {
  it("keeps the name frozen and announces the rewrite a change will cause", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: STORAGE },
      [`PUT ${ROUTE}/sites${Q}`]: {
        status: 200,
        body: { ...STORAGE, indexes: [], rewrite_announced: true },
      },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition", storage: "sites" });
    expect(await screen.findByLabelText("Name")).toBeDisabled();
    expect(screen.getByLabelText("Label")).toHaveValue("Sites");

    // Retirer l'index annonce la réécriture, comme l'aurait fait un changement de modèle.
    fireEvent.click(screen.getByText("Remove index 1"));
    fireEvent.click(screen.getByText("Save the storage"));

    expect(await screen.findByText(/rewrite every object and its index/)).toBeInTheDocument();
    expect(calls.find((c) => c.key === `PUT ${ROUTE}/sites${Q}`)?.body).toEqual({
      ...STORAGE,
      indexes: [],
    });
  });

  it("names the sources that keep a storage from being deleted", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: STORAGE },
      [`DELETE ${ROUTE}/sites${Q}`]: {
        status: 409,
        body: { detail: { code: "storage_utilise", sources: ["crm", "legacy"] } },
      },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition", storage: "sites" });
    fireEvent.click(await screen.findByText("Delete the storage"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Delete the storage"));

    expect(await screen.findByText(/crm, legacy/)).toBeInTheDocument();
  });

  it("deletes a free storage after confirmation and returns to the list", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: STORAGE },
      [`DELETE ${ROUTE}/sites${Q}`]: { status: 204 },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition", storage: "sites" });
    fireEvent.click(await screen.findByText("Delete the storage"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Delete the storage"));

    expect(await screen.findByText("No storage on this branch.")).toBeInTheDocument();
    expect(calls.some((c) => c.key === `DELETE ${ROUTE}/sites${Q}`)).toBe(true);
  });
});

describe("the property tree (24/10/2026)", () => {
  it("offers only values, never an array, an object or a path through an array", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition" });
    fireEvent.click(await screen.findByText("New storage"));
    fill("Label", "Sites");
    await screen.findByRole("option", { name: "shared/site" });
    fill("Object model", "shared/site");

    fireEvent.click(screen.getByRole("button", { name: "Functional key" }));
    const tree = await screen.findByRole("list", { name: "Functional key" });
    const names = within(tree)
      .getAllByRole("checkbox")
      .map((box) => box.closest("label")?.textContent ?? "");

    // « adresse » (objet) et « enseignes » (tableau) se lisent mais ne se cochent pas ;
    // « [0] » traverse un tableau, donc ne désigne pas une valeur unique.
    expect(names.some((n) => n.includes("code"))).toBe(true);
    expect(names.some((n) => n.includes("ville"))).toBe(true);
    expect(names.some((n) => n.startsWith("adresse"))).toBe(false);
    expect(names.some((n) => n.startsWith("enseignes"))).toBe(false);
    expect(names.some((n) => n.includes("[0]"))).toBe(false);
    // Le format est annoncé À CÔTÉ du type : « string » seul faisait passer un champ daté
    // pour du texte libre (Gael, 10/11/2026).
    expect(names.some((n) => n.includes("string · date-time"))).toBe(true);
    // Et les chemins que la doublure rend SANS format ne doivent rien afficher de plus :
    // sans le repli à vide, la légende dirait « string · undefined ».
    expect(names.some((n) => n.includes("undefined"))).toBe(false);
    // Elles restent affichées : c'est le chemin pour atteindre leurs enfants.
    expect(within(tree).getByTitle("$.adresse")).toBeInTheDocument();
  });

  it("says what to do when no model is chosen yet", async () => {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition" });
    fireEvent.click(await screen.findByText("New storage"));
    fireEvent.click(screen.getByRole("button", { name: "Functional key" }));

    expect(screen.getByText(/Choose the object model first/)).toBeInTheDocument();
  });
});

describe("the picker field (24/10/2026)", () => {
  function open() {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: STORAGE },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition", storage: "sites" });
  }

  it("shows what is selected while closed", async () => {
    open();

    expect(await screen.findByRole("button", { name: "Functional key" })).toHaveTextContent(
      "$.code",
    );
    expect(screen.getByRole("button", { name: "Columns of index par-ville" })).toHaveTextContent(
      "ville",
    );
  });

  it("closes on Escape without losing what was ticked", async () => {
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Functional key" }));
    await screen.findByRole("list", { name: "Functional key" });

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("list", { name: "Functional key" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Functional key" })).toHaveTextContent("$.code");
  });

  it("closes when the click lands outside it", async () => {
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Functional key" }));
    await screen.findByRole("list", { name: "Functional key" });

    fireEvent.mouseDown(document.body);

    expect(screen.queryByRole("list", { name: "Functional key" })).not.toBeInTheDocument();
  });
});

describe("additional indexes (24/10/2026)", () => {
  function open() {
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: STORAGE },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition", storage: "sites" });
  }

  it("adds as many indexes as needed", async () => {
    open();
    fireEvent.click(await screen.findByText("Add an index"));
    fireEvent.click(screen.getByText("Add an index"));

    // Un index existait déjà : on en a trois, et les noms proposés ne se doublent pas.
    expect(screen.getByLabelText("Name of index 2")).toHaveValue("index-1");
    expect(screen.getByLabelText("Name of index 3")).toHaveValue("index-2");
  });

  it("stops at three columns, by greying what cannot be ticked any more", async () => {
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Columns of index par-ville" }));
    const tree = await screen.findByRole("list", { name: "Columns of index par-ville" });

    // La colonne déjà choisie compte : il en reste deux à prendre.
    fireEvent.click(within(tree).getByRole("checkbox", { name: /code/ }));
    fireEvent.click(within(tree).getByRole("checkbox", { name: /pays/ }));

    const boxes = within(tree).getAllByRole("checkbox");
    const ticked = boxes.filter((b) => (b as HTMLInputElement).checked);
    expect(ticked).toHaveLength(3);
    // Plein : ce qui n'est pas coché ne peut plus l'être, mais reste décochable.
    for (const box of boxes) {
      expect(box).toHaveProperty("disabled", !(box as HTMLInputElement).checked);
    }
  });

  it("lets a column the model no longer offers be unticked, instead of trapping it", async () => {
    // Reproduit la copie d'écran du 01/11/2026 : « $.PhoneNumber » ne désignait rien dans
    // le modèle, la validation le refusait, et l'arbre ne le montrait pas — puisqu'il ne
    // rend que ce que le modèle offre. Rien ne permettait donc de l'enlever, et le seul
    // recours était de supprimer l'index entier.
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}/sites${Q}`]: {
        status: 200,
        body: {
          ...STORAGE,
          indexes: [{ name: "par-ville", columns: ["$.disparu", "$.adresse.ville"] }],
        },
      },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition", storage: "sites" });
    fireEvent.click(await screen.findByRole("button", { name: "Columns of index par-ville" }));
    const tree = await screen.findByRole("list", { name: "Columns of index par-ville" });

    const orphelin = within(tree).getByRole("checkbox", { name: /disparu/ });

    // Montré COCHÉ, et avec son chemin entier : c'est le chemin qui est fautif, et son
    // dernier segment seul ne permettrait pas de le reconnaître.
    expect(orphelin).toBeChecked();
    fireEvent.click(orphelin);
    expect(
      screen.getByRole("button", { name: "Columns of index par-ville" }),
    ).not.toHaveTextContent("disparu");
  });

  it("lets a functional key the model no longer offers be unticked too", async () => {
    // Même piège sur l'autre sélecteur : il n'y a pas de raison que la clé s'en sorte.
    mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body: { ...STORAGE, keys: ["$.parti"] } },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition", storage: "sites" });
    fireEvent.click(await screen.findByRole("button", { name: "Functional key" }));
    const tree = await screen.findByRole("list", { name: "Functional key" });

    fireEvent.click(within(tree).getByRole("checkbox", { name: /parti/ }));

    expect(screen.getByRole("button", { name: "Functional key" })).not.toHaveTextContent("parti");
  });

  it("removes an index with its columns", async () => {
    open();
    expect(await screen.findByLabelText("Name of index 1")).toHaveValue("par-ville");

    fireEvent.click(screen.getByText("Remove index 1"));

    expect(screen.queryByLabelText("Name of index 1")).not.toBeInTheDocument();
  });
});

describe("expiry rules (09/11/2026)", () => {
  function open(body: Record<string, unknown> = STORAGE) {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      ...MODELS,
      [`GET ${ROUTE}/sites${Q}`]: { status: 200, body },
      [`GET ${ROUTE}${Q}`]: { status: 200, body: [] },
      [`PUT ${ROUTE}/sites${Q}`]: {
        status: 200,
        body: { ...body, rewrite_announced: false },
      },
    });
    renderWorkspaces({ id: "retrait", view: "storages", branch: "edition", storage: "sites" });
    return calls;
  }

  it("offers only the columns an index declares, not the whole model", async () => {
    open();
    fireEvent.click(await screen.findByText("Add an expiry rule"));

    const choices = within(screen.getByLabelText("Date property of rule 1")).getAllByRole(
      "option",
    );

    // L'index déclaré ne porte que « $.adresse.ville » : le reste du modèle — « $.code »,
    // « $.rang » — n'est pas proposé, parce qu'une règle sans colonne réelle deviendrait
    // un parcours de table tout en désignant des suppressions.
    expect(choices.map((o) => o.getAttribute("value"))).toEqual(["", "$.adresse.ville"]);
  });

  it("says in clear that the rule DELETES, with the property and the delay", async () => {
    open();
    fireEvent.click(await screen.findByText("Add an expiry rule"));
    fireEvent.change(screen.getByLabelText("Date property of rule 1"), {
      target: { value: "$.adresse.ville" },
    });
    fireEvent.change(screen.getByLabelText("Delay in days of rule 1"), { target: { value: "10" } });

    // Une règle de suppression qui ne dit pas qu'elle supprime n'est pas lisible.
    expect(
      screen.getByText(/will be DELETED once “\$\.adresse\.ville” plus 10 days have passed/),
    ).toBeInTheDocument();
  });

  it("sends the rule with the declaration, and takes it back out", async () => {
    const calls = open();
    fireEvent.click(await screen.findByText("Add an expiry rule"));
    fireEvent.change(screen.getByLabelText("Date property of rule 1"), {
      target: { value: "$.adresse.ville" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save the storage" }));
    expect(await screen.findByText("Storage saved.")).toBeInTheDocument();

    expect(calls.find((c) => c.key === `PUT ${ROUTE}/sites${Q}`)?.body).toEqual({
      ...STORAGE,
      expiries: [{ property: "$.adresse.ville", days: 30 }],
    });

    fireEvent.click(screen.getByText("Remove rule 1"));
    expect(screen.queryByLabelText("Date property of rule 1")).not.toBeInTheDocument();
  });

  it("asks for an index first when no column is declared", async () => {
    open({ ...STORAGE, indexes: [] });

    // Pas de bouton qui ne mène à rien : l'écran dit par quoi commencer.
    expect(
      await screen.findByText(/add an index on the date property first/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Add an expiry rule")).not.toBeInTheDocument();
  });
});
