import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const Q = "?branch=edition";
const REFERENCE = `/api/workspaces/retrait/account-reference${Q}`;
const STORAGES = `/api/workspaces/retrait/storages${Q}`;
const TWO = [
  { name: "comptes", label: "Comptes", model: "shared/compte", keys: ["$.identifiant"] },
  { name: "sites", label: "Sites", model: "shared/site", keys: ["$.code"] },
];
const MODES = ["whatsapp", "viber", "signal", "sms", "email"];
// Rendus par le serveur à CHAQUE lecture : la doublure les porte donc aussi, sans quoi
// elle décrirait un contrat qui n'existe pas.
const SURFACE = { delivery: null, modes: MODES, served_modes: ["email"] };
const NONE = { storage: null, model: null, problem: null, ...SURFACE };
const PATHS = `/api/workspaces/retrait/data-models/shared/compte/paths${Q}`;
const COMPTE_PATHS = {
  paths: [
    { path: "$.identifiant", type: "string", description: "" },
    { path: "$.email", type: "string", description: "Adresse" },
    { path: "$.adresses", type: "array", description: "" },
    { path: "$.postale", type: "object", description: "" },
  ],
};

function open(api: Record<string, unknown>) {
  const calls = mockApi({
    ...HELD,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    [`GET ${STORAGES}`]: { status: 200, body: TWO },
    [`GET ${PATHS}`]: { status: 200, body: COMPTE_PATHS },
    ...api,
  });
  renderWorkspaces({ id: "retrait", view: "accountReference", branch: "edition" });
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AccountReferenceScreen (31/10/2026)", () => {
  it("designates the storage with a single dropdown, and shows the model it declares", async () => {
    // La correction de Gael : UNE liste déroulante. Le modèle s'affiche, il ne se choisit
    // pas — un second sélecteur ferait saisir deux fois la même information.
    const calls = open({
      [`GET ${REFERENCE}`]: { status: 200, body: NONE },
      [`PUT ${REFERENCE}`]: {
        status: 200,
        body: { storage: "comptes", model: "shared/compte", problem: null, ...SURFACE },
      },
    });
    expect(
      await screen.findByText("No account reference is declared on this branch."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/model/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Accounts storage"), { target: { value: "comptes" } });
    fireEvent.click(screen.getByText("Save the reference"));

    expect(await screen.findByText("Account reference saved.")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `PUT ${REFERENCE}`)?.body).toEqual({
      storage: "comptes",
      delivery: null,
    });
  });

  it("says the setting is declared and not yet served", async () => {
    // Sans cette phrase, l'écran laisse croire qu'un code part déjà.
    open({ [`GET ${REFERENCE}`]: { status: 200, body: NONE } });

    expect(await screen.findByText(/not yet served/i)).toBeInTheDocument();
  });

  it("names the storages that exist when the one asked for does not", async () => {
    open({
      [`GET ${REFERENCE}`]: { status: 200, body: NONE },
      [`PUT ${REFERENCE}`]: {
        status: 422,
        body: {
          detail: { code: "storage_inconnu", storage: "comptes", existants: ["sites"] },
        },
      },
    });
    fireEvent.change(await screen.findByLabelText("Accounts storage"), {
      target: { value: "comptes" },
    });
    fireEvent.click(screen.getByText("Save the reference"));

    expect(await screen.findByText(/The ones that do: sites\./)).toBeInTheDocument();
  });

  it("explains an empty list instead of offering nothing to choose", async () => {
    const calls = mockApi({
      ...HELD,
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      [`GET ${STORAGES}`]: { status: 200, body: [] },
      [`GET ${REFERENCE}`]: { status: 200, body: NONE },
    });
    renderWorkspaces({ id: "retrait", view: "accountReference", branch: "edition" });

    expect(await screen.findByText(/No storage on this branch: declare one/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Accounts storage")).not.toBeInTheDocument();
    expect(calls).toBeDefined();
  });

  it("shows a storage that disappeared without rewriting the setting", async () => {
    open({
      [`GET ${REFERENCE}`]: {
        status: 200,
        body: {
          storage: "comptes",
          model: null,
          problem: {
            path: "comptes/reference.yaml",
            code: "storage_inconnu",
            detail: "comptes",
          },
          ...SURFACE,
        },
      },
    });

    expect(
      await screen.findByText(/designates the storage “comptes”, which this branch does not carry/),
    ).toBeInTheDocument();
    // Le réglage reste montré tel quel : l'écran signale, il ne corrige pas.
    expect(screen.getByLabelText("Accounts storage")).toHaveValue("comptes");
  });

  it("names an unreadable file instead of pretending nothing is declared", async () => {
    open({
      [`GET ${REFERENCE}`]: {
        status: 200,
        body: {
          storage: null,
          model: null,
          problem: {
            path: "comptes/reference.yaml",
            code: "fichier_illisible",
            detail: null,
          },
          ...SURFACE,
        },
      },
    });

    expect(
      await screen.findByText(/comptes\/reference\.yaml exists but does not have the expected/),
    ).toBeInTheDocument();
  });

  it("offers no write on the base branch", async () => {
    const calls = mockApi({
      "GET /api/workspaces": { status: 200, body: [WORKING] },
      "GET /api/workspaces/retrait/storages?branch=atelier": { status: 200, body: TWO },
      "GET /api/workspaces/retrait/data-models/shared/compte/paths?branch=atelier": {
        status: 200,
        body: COMPTE_PATHS,
      },
      "GET /api/workspaces/retrait/account-reference?branch=atelier": {
        status: 200,
        body: { storage: "comptes", model: "shared/compte", problem: null, ...SURFACE },
      },
    });
    renderWorkspaces({ id: "retrait", view: "accountReference", branch: "atelier" });

    expect(await screen.findByLabelText("Accounts storage")).toBeDisabled();
    expect(screen.queryByText("Save the reference")).not.toBeInTheDocument();
    expect(calls).toBeDefined();
  });

  it("offers the five modes but lets only the served one be chosen", async () => {
    // « pour le moment on implémentera que le mail » : les quatre autres restent
    // VISIBLES et désactivés — les cacher ferait croire qu'ils ne sont pas prévus.
    open({
      [`GET ${REFERENCE}`]: {
        status: 200,
        body: { storage: "comptes", model: "shared/compte", problem: null, ...SURFACE },
      },
    });
    const mode = await screen.findByLabelText("Code delivery mode");
    const offered = within(mode).getAllByRole("option");

    expect(offered.map((o) => o.textContent)).toEqual([
      "Choose…",
      "WhatsApp — not served yet",
      "Viber — not served yet",
      "Signal — not served yet",
      "SMS — not served yet",
      "Email",
    ]);
    expect(offered.filter((o) => !(o as HTMLOptionElement).disabled)).toHaveLength(2);
  });

  it("asks for the address field only once a mode is chosen, and saves both", async () => {
    const calls = open({
      [`GET ${REFERENCE}`]: {
        status: 200,
        body: { storage: "comptes", model: "shared/compte", problem: null, ...SURFACE },
      },
      [`PUT ${REFERENCE}`]: {
        status: 200,
        body: {
          storage: "comptes",
          model: "shared/compte",
          problem: null,
          ...SURFACE,
          delivery: { mode: "email", field: "$.email" },
        },
      },
    });
    await screen.findByLabelText("Code delivery mode");
    // Tant qu'aucun mode n'est choisi, il n'y a rien à demander.
    expect(screen.queryByLabelText("Field holding the delivery address")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Code delivery mode"), {
      target: { value: "email" },
    });
    const field = await screen.findByLabelText("Field holding the delivery address");
    await within(field).findByRole("option", { name: "$.email" });
    fireEvent.change(field, { target: { value: "$.email" } });
    fireEvent.click(screen.getByText("Save the reference"));

    await screen.findByText("Account reference saved.");
    expect(calls.find((c) => c.key === `PUT ${REFERENCE}`)?.body).toEqual({
      storage: "comptes",
      delivery: { mode: "email", field: "$.email" },
    });
  });

  it("offers only the plain properties as an address", async () => {
    // Un tableau ou un objet ne s'envoie pas : le serveur les refuse, donc l'écran ne
    // les propose pas — sinon la personne choisit ce qui sera rejeté.
    open({
      [`GET ${REFERENCE}`]: {
        status: 200,
        body: {
          storage: "comptes",
          model: "shared/compte",
          problem: null,
          ...SURFACE,
          delivery: { mode: "email", field: "$.email" },
        },
      },
    });
    const field = await screen.findByLabelText("Field holding the delivery address");
    // Les chemins arrivent par une seconde requête : sans cette attente, le test
    // mesurerait une liste encore vide et passerait pour la mauvaise raison.
    await within(field).findByRole("option", { name: "$.email" });

    expect(within(field).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Choose…",
      "$.identifiant",
      "$.email",
    ]);
  });

  it("says a mode that is not served yet instead of showing the raw code", async () => {
    open({
      [`GET ${REFERENCE}`]: {
        status: 200,
        body: {
          storage: "comptes",
          model: "shared/compte",
          ...SURFACE,
          delivery: { mode: "viber", field: "$.email" },
          problem: {
            path: "comptes/reference.yaml",
            code: "mode_non_servi",
            detail: "viber",
          },
        },
      },
    });

    expect(
      await screen.findByText(/declares the delivery mode “viber”, which is not served yet/),
    ).toBeInTheDocument();
  });

  it("drops the address field when the storage changes", async () => {
    // Changer de stockage change le modèle : garder l'ancien champ le ferait pointer
    // dans le vide, et le serveur le refuserait au moment d'enregistrer.
    const calls = open({
      [`GET ${REFERENCE}`]: {
        status: 200,
        body: {
          storage: "comptes",
          model: "shared/compte",
          problem: null,
          ...SURFACE,
          delivery: { mode: "email", field: "$.email" },
        },
      },
      [`GET /api/workspaces/retrait/data-models/shared/site/paths${Q}`]: {
        status: 200,
        body: { paths: [{ path: "$.code", type: "string", description: "" }] },
      },
      [`PUT ${REFERENCE}`]: { status: 200, body: NONE },
    });
    await screen.findByLabelText("Field holding the delivery address");

    fireEvent.change(screen.getByLabelText("Accounts storage"), { target: { value: "sites" } });
    expect(screen.queryByLabelText("Field holding the delivery address")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Save the reference"));
    await screen.findByText("Account reference saved.");
    expect(calls.find((c) => c.key === `PUT ${REFERENCE}`)?.body).toEqual({
      storage: "sites",
      delivery: null,
    });
  });
});
