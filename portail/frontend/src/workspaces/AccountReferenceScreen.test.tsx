import { fireEvent, screen } from "@testing-library/react";

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
const NONE = { storage: null, model: null, problem: null };

function open(api: Record<string, unknown>) {
  const calls = mockApi({
    ...HELD,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    [`GET ${STORAGES}`]: { status: 200, body: TWO },
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
        body: { storage: "comptes", model: "shared/compte", problem: null },
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
      "GET /api/workspaces/retrait/account-reference?branch=atelier": {
        status: 200,
        body: { storage: "comptes", model: "shared/compte", problem: null },
      },
    });
    renderWorkspaces({ id: "retrait", view: "accountReference", branch: "atelier" });

    expect(await screen.findByLabelText("Accounts storage")).toBeDisabled();
    expect(screen.queryByText("Save the reference")).not.toBeInTheDocument();
    expect(calls).toBeDefined();
  });
});
