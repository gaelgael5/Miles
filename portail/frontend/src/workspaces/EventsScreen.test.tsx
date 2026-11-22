import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import {
  CONFIGURED,
  eventPerimeter,
  fill,
  HELD,
  modelListing,
  renderWorkspaces,
} from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/workflow-events";
const MODELS = "/api/workspaces/retrait/data-models";
const DOMAINS = "/api/workspaces/retrait/domains";
const NO_VERSION = {
  "GET /api/workspaces/retrait/versions?branch=edition": { status: 200, body: [] },
};
// Un type d'event tel que le portail le sert : une DÉCLARATION, pas un document.
const DEMANDE = {
  scope: "shared",
  name: "demande_soumise",
  label: "Demande soumise",
  model: "shared/models/demande.yaml",
  model_scope: "shared",
  model_name: "demande",
  // L'ordre est DISCRIMINANT : un tri à l'affichage changerait le dédoublonnage.
  unique: ["Tracking", "ExternalId"],
  model_missing: false,
  // Hérite de l'event de base : aucun renvoi écrit, le moteur applique sa racine
  // d'office (décision 2 du 22/11/2026).
  parents: [],
};
// Le type d'un AUTRE périmètre, aux valeurs toutes différentes : un seul périmètre
// laisserait passer un écran qui ignore la sélection (critère 10 de la story 8a9ff6bc).
const VALIDATION = {
  scope: "achats",
  name: "commande_validee",
  label: "Commande validée",
  model: "domains/achats/models/commande.yaml",
  model_scope: "achats",
  model_name: "commande",
  unique: ["Reference"],
  model_missing: false,
  // DISCRIMINANT : celui-ci hérite du payload de l'autre périmètre — l'héritage traverse
  // les périmètres, et l'écran doit nommer l'event dont il vient.
  parents: ["shared/models/demande.yaml"],
};
const DEMANDE_MODEL = {
  scope: "shared",
  name: "demande",
  path: "shared/models/demande.yaml",
  label: "Demande",
  version: 1,
};
// Tel que le portail le sert : le JSON Schema du moteur, pas une liste de noms.
const SOCLE = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  title: "urban-workflow base event",
  type: "object",
  required: ["Name"],
  properties: {
    Name: { type: "string", minLength: 1 },
    ExternalId: { type: "string" },
  },
};

function routes(extra: Record<string, unknown> = {}) {
  return {
    ...HELD,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    ...NO_VERSION,
    [`GET ${ROUTE}?branch=edition`]: {
      status: 200,
      body: [eventPerimeter("shared", [DEMANDE]), eventPerimeter("achats", [VALIDATION])],
    },
    [`GET ${ROUTE}/socle?branch=edition`]: { status: 200, body: SOCLE },
    [`GET ${MODELS}?branch=edition`]: { status: 200, body: modelListing([DEMANDE_MODEL]) },
    [`GET ${DOMAINS}?branch=edition`]: { status: 200, body: [{ name: "achats" }] },
    ...extra,
  } as never;
}

async function openEvents(extra: Record<string, unknown> = {}) {
  const calls = mockApi(routes(extra));
  renderWorkspaces({ id: "retrait", view: "events", branch: "edition" });
  await screen.findByRole("heading", { name: "Event types — Retrait de colis" });
  return calls;
}

/** L'écran d'UN périmètre, tel que le menu l'ouvre (story 8a9ff6bc, critère 2). */
async function openPerimeter(scope: string, extra: Record<string, unknown> = {}) {
  const calls = mockApi(routes(extra));
  renderWorkspaces({ id: "retrait", view: "events", branch: "edition", scope });
  return calls;
}

function section(name: string): HTMLElement {
  return screen.getByRole("region", { name: `Perimeter ${name}` });
}

/**
 * Choisit le PARENT du nouvel event, en attendant que les types soient arrivés.
 *
 * Sans cette attente, le `<select>` existe déjà mais sans ses options : la valeur posée
 * ne correspond à aucune, et le navigateur la laisse sur la première — « l'event de
 * base » —, donc le test passerait en prouvant le contraire de ce qu'il affirme. La
 * leçon est de l'ancienne version de ce fichier, qui attendait les modèles (14/11/2026).
 */
async function pickParent(value = "shared/demande_soumise") {
  // DANS le formulaire : chaque ligne de la liste porte elle aussi un choix de parent,
  // celui de sa redirection. Une recherche globale trouverait les deux.
  const form = screen.getByRole("form", { name: "New event type" });
  await within(form).findByRole("option", { name: /Demande soumise/ });
  fireEvent.change(within(form).getByLabelText("Inherits from"), { target: { value } });
}

describe("the event type referential", () => {
  it("lists each declaration with the DSL name, its payload and its keys IN ORDER", async () => {
    await openEvents();

    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    // Le NOM du DSL : la seule chose qu'un script de workflow connaisse de cet écran.
    expect(within(row).getByText("demande_soumise")).toBeInTheDocument();
    expect(within(row).getByText("shared/models/demande.yaml")).toBeInTheDocument();
    // L'ordre tel qu'il a été saisi, et pas trié : le moteur en dérive le hash
    // d'anti-doublon par concaténation.
    expect(within(row).getByText("Tracking, ExternalId")).toBeInTheDocument();
  });

  it("proposes an underscored name, because the engine's DSL rejects hyphens", async () => {
    // La règle est MESURÉE (urban-workflow 0.2.1, 11/11/2026) : sans ce remplacement,
    // « Demande soumise » proposerait « demande-soumise », refusé par le serveur.
    await openEvents();
    fireEvent.click(await screen.findByText("Declare an event type"));

    fill("Label", "Demande soumise");

    expect(screen.getByLabelText("DSL name")).toHaveValue("demande_soumise");
  });

  it("creates the type deriving from the BASE event, without naming any model", async () => {
    // Le geste du 19/11/2026 : on ne choisit plus un modèle, on crée l'event. Sans parent,
    // AUCUN renvoi n'est demandé — le moteur applique sa racine d'office.
    const calls = await openEvents({
      [`POST ${ROUTE}/declarations?branch=edition`]: { status: 201, body: DEMANDE },
    });
    fireEvent.click(await screen.findByText("Declare an event type"));
    fill("Label", "Demande soumise");
    fill("Uniqueness keys", " Tracking , ExternalId ");
    fireEvent.click(screen.getByRole("button", { name: "Declare the event type" }));

    await screen.findByText("Declare an event type");
    expect(calls.find((c) => c.key === `POST ${ROUTE}/declarations?branch=edition`)?.body).toEqual({
      scope: "shared",
      label: "Demande soumise",
      slug: "demande_soumise",
      // Les espaces de saisie retirés, l'ORDRE conservé.
      unique: ["Tracking", "ExternalId"],
    });
  });

  it("creates a type that INHERITS from another event", async () => {
    const calls = await openEvents({
      [`POST ${ROUTE}/declarations?branch=edition`]: { status: 201, body: DEMANDE },
    });
    fireEvent.click(await screen.findByText("Declare an event type"));
    fill("Label", "Demande close");
    await pickParent();
    fireEvent.click(screen.getByRole("button", { name: "Declare the event type" }));

    await screen.findByText("Declare an event type");
    const sent = calls.find((c) => c.key === `POST ${ROUTE}/declarations?branch=edition`);
    expect(sent?.body).toEqual({
      scope: "shared",
      label: "Demande close",
      slug: "demande_close",
      parent_scope: "shared",
      parent_name: "demande_soumise",
      unique: [],
    });
  });

  it("names the base properties a uniqueness key may use without being in the model", async () => {
    // `ExternalId` est la clé d'anti-doublon la plus courante et ne vient pas du modèle :
    // sans cette aide, la personne essaie, se fait refuser, et ne sait pas quoi écrire.
    await openEvents();
    fireEvent.click(await screen.findByText("Declare an event type"));

    expect(await screen.findByText(/ExternalId, Name/)).toBeInTheDocument();
  });

  it("says why a name the DSL would reject is refused", async () => {
    await openEvents({
      [`POST ${ROUTE}/declarations?branch=edition`]: {
        status: 422,
        body: { detail: { field: "name" } },
      },
    });
    fireEvent.click(await screen.findByText("Declare an event type"));
    fill("Label", "Demande");
    fill("DSL name", "demande-soumise");
    fireEvent.click(screen.getByRole("button", { name: "Declare the event type" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/rejects hyphens/);
  });

  it("names the rule the designated model breaks, rather than « not conforming »", async () => {
    await openEvents({
      [`POST ${ROUTE}/declarations?branch=edition`]: {
        status: 422,
        body: {
          detail: {
            code: "declaration_non_conforme",
            problems: [{ path: "additionalProperties", code: "schema_ferme", detail: null }],
          },
        },
      },
    });
    fireEvent.click(await screen.findByText("Declare an event type"));
    fill("Label", "Demande");
    fireEvent.click(screen.getByRole("button", { name: "Declare the event type" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/cannot carry an event type/);
    expect(alert).toHaveTextContent(/no real payload would pass/);
  });

  it("flags a declaration whose payload model has disappeared", async () => {
    // C'est ce qui bloque l'enregistrement d'une version : le dire ICI, c'est le dire là
    // où on peut la corriger.
    await openEvents({
      [`GET ${ROUTE}?branch=edition`]: {
        status: 200,
        body: [eventPerimeter("shared", [{ ...DEMANDE, model_missing: true }])],
      },
    });

    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    expect(within(row).getByText("model missing")).toBeInTheDocument();
  });

  it("does not flag a declaration whose model is there", async () => {
    // Discriminant : sans ce contrôle, un badge affiché toujours passerait le test ci-dessus.
    await openEvents();

    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    expect(within(row).queryByText("model missing")).not.toBeInTheDocument();
  });

  it("opens the payload in the MODEL screen, since it is an ordinary model", async () => {
    await openEvents({
      [`GET ${MODELS}/shared/demande?branch=edition`]: {
        status: 200,
        body: { ...DEMANDE_MODEL, content: "title: Demande\ntype: object\nproperties: {}\n" },
      },
    });
    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;

    fireEvent.click(within(row).getByText("shared/models/demande.yaml"));

    // L'éditeur de schéma d'event n'existe plus : c'est l'écran des modèles qui édite.
    expect(await screen.findByRole("heading", { name: "Demande" })).toBeInTheDocument();
  });

  it("changes the label and the keys, keeps the name AND the declared model", async () => {
    const calls = await openEvents({
      [`PUT ${ROUTE}/shared/demande_soumise?branch=edition`]: { status: 200, body: DEMANDE },
    });
    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Edit" }));

    // Le payload appartient à l'event depuis le 19/11/2026 : il ne se choisit plus ici.
    expect(screen.queryByLabelText("Payload model")).toBeNull();
    fill("Label", "Demande reçue");
    fill("Uniqueness keys", "ExternalId");
    fireEvent.click(screen.getByRole("button", { name: "Save the declaration" }));

    // `findAll` : chaque périmètre a son bouton « Edit » depuis que l'écran les montre
    // tous. On attend que le formulaire soit refermé, pas qu'un bouton soit unique.
    await screen.findAllByRole("button", { name: "Edit" });
    const sent = calls.find((c) => c.key === `PUT ${ROUTE}/shared/demande_soumise?branch=edition`);
    expect(sent?.body).toEqual({
      label: "Demande reçue",
      model_scope: "shared",
      model_name: "demande",
      unique: ["ExternalId"],
    });
  });

  it("reports an unreadable artefact at the engine's own position, on a write", async () => {
    // Retouché hors de Miles, ou produit par un autre outil : le moteur refuserait de
    // charger tout le répertoire. Un « fichier invalide » sans position ne se corrige pas.
    // Sur une ÉCRITURE : depuis le 17/11/2026 la lecture, elle, rend le périmètre avec son
    // erreur plutôt que de refuser en bloc — un geste d'écriture, lui, refuse toujours,
    // pour ne pas écrire par-dessus ce qu'on n'a pas su relire.
    await openEvents({
      [`POST ${ROUTE}/declarations?branch=edition`]: {
        status: 422,
        body: {
          detail: {
            code: "artefact_illisible",
            problems: [{ line: 2, column: 13, message: "mismatched input ';'" }],
          },
        },
      },
    });
    fireEvent.click(await screen.findByText("Declare an event type"));
    fill("Label", "Demande");
    fireEvent.click(screen.getByRole("button", { name: "Declare the event type" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/would refuse to load the whole directory/);
    expect(alert).toHaveTextContent(/line 2, column 13/);
    expect(alert).toHaveTextContent(/mismatched input/);
  });

  it("lists both perimeters, each with its artefact and its own declarations", async () => {
    await openEvents();

    await screen.findByText("Demande soumise");
    const shared = section("Shared");
    const achats = section("achats");
    // Le FICHIER de chaque périmètre : c'est lui qu'on ouvre pour comprendre, et lui que
    // le moteur chargera.
    expect(within(shared).getByText("shared/shared.wf")).toBeInTheDocument();
    expect(within(achats).getByText("domains/achats/achats.wf")).toBeInTheDocument();
    // Et chaque type sous SON périmètre, pas sous l'autre.
    expect(within(shared).getByText("demande_soumise")).toBeInTheDocument();
    expect(within(shared).queryByText("commande_validee")).not.toBeInTheDocument();
    expect(within(achats).getByText("commande_validee")).toBeInTheDocument();
    expect(within(achats).getByText("Reference")).toBeInTheDocument();
  });

  it("shows only the perimeter the menu opened", async () => {
    await openPerimeter("achats");

    expect(
      await screen.findByRole("heading", { name: "Event types — achats" }),
    ).toBeInTheDocument();
    // Attendu : le titre vient de la SÉLECTION et s'affiche avant la lecture ; sans cette
    // attente le test mesurerait l'écran d'avant la réponse.
    const achats = await screen.findByRole("region", { name: "Perimeter achats" });
    expect(within(achats).getByText("commande_validee")).toBeInTheDocument();
    // Discriminant : sans la sélection, l'écran montrerait les deux.
    expect(screen.queryByRole("region", { name: "Perimeter Shared" })).not.toBeInTheDocument();
    expect(screen.queryByText("demande_soumise")).not.toBeInTheDocument();
  });

  it("names the unreadable artefact and keeps the other perimeter listed", async () => {
    // Critères 5 et 7 : un périmètre cassé ne noircit pas tout le bloc, et ce qui se lit
    // ailleurs se lit quand même.
    await openEvents({
      [`GET ${ROUTE}?branch=edition`]: {
        status: 200,
        body: [
          eventPerimeter("shared", [DEMANDE]),
          eventPerimeter("achats", [], [{ line: 2, column: 13, message: "mismatched input ';'" }]),
        ],
      },
    });

    await screen.findByText("Demande soumise");
    const achats = within(section("achats")).getByRole("note");
    expect(achats).toHaveTextContent(/domains\/achats\/achats\.wf/);
    expect(achats).toHaveTextContent(/line 2, column 13/);
    expect(achats).toHaveTextContent(/mismatched input/);
    // L'autre périmètre, lui, liste toujours.
    expect(within(section("Shared")).getByText("demande_soumise")).toBeInTheDocument();
  });

  it("invites to declare in a perimeter whose artefact does not exist yet", async () => {
    // Critère 6 : « aucun type » et « illisible » sont deux états, et pas une page blanche.
    await openEvents({
      [`GET ${ROUTE}?branch=edition`]: {
        status: 200,
        body: [eventPerimeter("shared", [DEMANDE]), eventPerimeter("achats")],
      },
    });

    await screen.findByText("Demande soumise");
    const achats = section("achats");
    expect(achats).toHaveTextContent(/declares no event type/);
    expect(within(achats).queryByRole("note")).not.toBeInTheDocument();
  });

  it("declares in the perimeter being viewed, without asking for it again", async () => {
    const calls = await openPerimeter("achats", {
      [`POST ${ROUTE}/declarations?branch=edition`]: { status: 201, body: VALIDATION },
    });
    fireEvent.click(await screen.findByText("Declare an event type"));
    fill("Label", "Commande validée");
    // Un type transverse est un parent visible d'un périmètre de domaine ; l'inverse non.
    await pickParent();
    fireEvent.click(screen.getByRole("button", { name: "Declare the event type" }));

    await screen.findByText("Declare an event type");
    const sent = calls.find((c) => c.key === `POST ${ROUTE}/declarations?branch=edition`);
    // `achats` et non « shared » : déclarer depuis l'écran d'un périmètre et devoir le
    // rechoisir ferait écrire dans le mauvais artefact d'un clic distrait.
    expect((sent?.body as { scope: string }).scope).toBe("achats");
  });
});

/**
 * L'HÉRITAGE : l'event de base en tête, le lien affiché en bas de chaque type, et sa
 * redirection (story 6064ce93, demande de Gael du 19/11/2026).
 */
describe("the inheritance of an event type", () => {
  it("shows the BASE event first, read-only, served by the portal", async () => {
    await openEvents();

    const base = await screen.findByRole("region", { name: "Base event" });
    expect(base).toHaveTextContent("read-only");
    // Les champs du moteur y sont, dans le MÊME éditeur visuel que les champs métier :
    // montré autrement, le socle se lirait comme une annexe et on ne verrait plus qu'un
    // event en DÉRIVE (relevé par Gael le 11/11/2026).
    expect(within(base).getByText("Name")).toBeInTheDocument();
    expect(within(base).getByText("ExternalId")).toBeInTheDocument();
    // Aucun geste de l'écran ne le touche : ni modifier, ni supprimer, ni rediriger son
    // héritage — il n'a pas de parent, il EST la racine.
    expect(within(base).queryByRole("button", { name: "Edit" })).toBeNull();
    expect(within(base).queryByRole("button", { name: "Delete" })).toBeNull();
    expect(within(base).queryByLabelText("Redirect inheritance to")).toBeNull();
  });

  it("says, under each type, which event its payload derives from", async () => {
    await openEvents();

    const derived = (await screen.findByText("Commande validée")).closest("li") as HTMLElement;
    // `VALIDATION` hérite du payload de `DEMANDE`, qui vit dans un AUTRE périmètre :
    // l'écran nomme l'event, pas le chemin du modèle.
    expect(within(derived).getByText(/Inherits from “Demande soumise” \(demande_soumise\)/));
    const root = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    expect(within(root).getByText(/Inherits from the base event/));
  });

  it("redirects the inheritance toward another event", async () => {
    const calls = await openEvents({
      [`PUT ${ROUTE}/achats/commande_validee/parent?branch=edition`]: {
        status: 200,
        body: { ...VALIDATION, parents: [] },
      },
    });
    const row = (await screen.findByText("Commande validée")).closest("li") as HTMLElement;

    // Vers l'event de base : le choix qui RETIRE le renvoi du fichier.
    fireEvent.change(within(row).getByLabelText("Redirect inheritance to"), {
      target: { value: "" },
    });
    fireEvent.click(within(row).getByRole("button", { name: "Redirect" }));

    const key = `PUT ${ROUTE}/achats/commande_validee/parent?branch=edition`;
    await screen.findByText(/Inherits from the base event/);
    // Un corps vide, et non un parent nul : c'est la route qui dit « l'event de base ».
    expect(calls.find((c) => c.key === key)?.body).toEqual({});
  });

  it("does not offer to redirect toward the type itself", async () => {
    await openEvents();

    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    const select = within(row).getByLabelText("Redirect inheritance to");

    // Lui-même exclu : le serveur le refuserait (`heritage_recursif`), et le proposer
    // inviterait à un geste qui ne peut pas aboutir.
    expect(within(select).queryByRole("option", { name: /demande_soumise/ })).toBeNull();
    expect(within(select).getByRole("option", { name: "The base event" })).toBeInTheDocument();
  });

  it("names the LOOP when the server refuses a recursive inheritance", async () => {
    // Deux types transverses, dont le second hérite déjà du premier : rediriger le
    // premier vers le second ferme la boucle, et c'est le serveur qui en est l'arbitre.
    const CLOSE = {
      ...DEMANDE,
      name: "demande_close",
      label: "Demande close",
      model: "shared/models/cloture.yaml",
      model_name: "cloture",
      parents: ["shared/models/demande.yaml"],
      unique: [],
    };
    const calls = await openEvents({
      [`GET ${ROUTE}?branch=edition`]: {
        status: 200,
        body: [eventPerimeter("shared", [DEMANDE, CLOSE]), eventPerimeter("achats", [])],
      },
      [`PUT ${ROUTE}/shared/demande_soumise/parent?branch=edition`]: {
        status: 422,
        body: {
          detail: {
            code: "declaration_non_conforme",
            problems: [
              {
                path: "allOf",
                code: "heritage_recursif",
                detail: "shared/demande → achats/commande → shared/demande",
              },
            ],
          },
        },
      },
    });
    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    fireEvent.change(within(row).getByLabelText("Redirect inheritance to"), {
      target: { value: "shared/demande_close" },
    });
    fireEvent.click(within(row).getByRole("button", { name: "Redirect" }));

    const alert = await screen.findByRole("alert");
    // La boucle, en clair : c'est elle qui dit quoi corriger.
    expect(alert).toHaveTextContent(/shared\/demande → achats\/commande → shared\/demande/);
    expect(alert).toHaveTextContent(/loops/);
    expect(calls.some((c) => c.key.startsWith("PUT"))).toBe(true);
  });

  it("tells when the parent is a model that no event carries", async () => {
    // Un `allOf: $ref` écrit à la main vers un modèle ordinaire : l'écran ne doit pas dire
    // « hérite de l'event de base », ce qui serait faux, ni rester muet.
    await openEvents({
      [`GET ${ROUTE}?branch=edition`]: {
        status: 200,
        body: [
          eventPerimeter("shared", [{ ...DEMANDE, parents: ["shared/models/colis.yaml"] }]),
          eventPerimeter("achats", []),
        ],
      },
    });

    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    expect(within(row).getByText(/Inherits from model shared\/models\/colis\.yaml/));
  });
});
