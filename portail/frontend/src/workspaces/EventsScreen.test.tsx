import { fireEvent, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { mockApi } from "@miles/socle-web/testing";
import { CONFIGURED, HELD, fill, renderWorkspaces } from "./workspaceFixtures";

const WORKING = { ...CONFIGURED, work_branch: "back/retrait/atelier" };
const ROUTE = "/api/workspaces/retrait/workflow-events";
const MODELS = "/api/workspaces/retrait/data-models";
const DOMAINS = "/api/workspaces/retrait/domains";
const NO_VERSION = {
  "GET /api/workspaces/retrait/versions?branch=edition": { status: 200, body: [] },
};
const DEMANDE = {
  scope: "shared",
  name: "demande_soumise",
  path: "shared/events/demande_soumise.yaml",
  label: "Demande soumise",
  version: 1,
  // Discriminant : le badge « socle seul » ne doit PAS s'afficher sur un événement qui
  // porte des champs métier.
  base_only: false,
};
const NU = { ...DEMANDE, name: "ping", path: "shared/events/ping.yaml", label: "Ping", base_only: true };
const BLANK =
  "$schema: https://json-schema.org/draft/2020-12/schema\n" +
  "$id: miles:/events/shared/demande_soumise\ntitle: Demande soumise\ntype: object\nproperties: {}\n";
// Tel que le portail le sert : le JSON Schema du moteur, pas une liste de noms.
const SOCLE = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  title: "urban-workflow base event",
  type: "object",
  required: ["Name"],
  properties: {
    Name: { type: "string", minLength: 1 },
    ExternalId: { type: "string" },
    IntegrationDate: { type: "string", format: "date-time", readOnly: true },
  },
};

function routes(extra: Record<string, unknown> = {}) {
  return {
    ...HELD,
    "GET /api/workspaces": { status: 200, body: [WORKING] },
    ...NO_VERSION,
    [`GET ${ROUTE}?branch=edition`]: { status: 200, body: [DEMANDE] },
    [`GET ${DOMAINS}?branch=edition`]: { status: 200, body: [{ name: "achats" }] },
    ...extra,
  } as never;
}

async function openEvents(extra: Record<string, unknown> = {}) {
  const calls = mockApi(routes(extra));
  renderWorkspaces({ id: "retrait", view: "events", branch: "edition" });
  await screen.findByRole("heading", { name: "Events — Retrait de colis" });
  return calls;
}

describe("the event referential", () => {
  it("lists the declared events with the name a DEFINE EVENT would use", async () => {
    await openEvents();

    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    // Le NOM du DSL, et non le chemin : c'est la seule chose qu'un script connaisse.
    expect(within(row).getByText("demande_soumise")).toBeInTheDocument();
    expect(within(row).getByText("Shared")).toBeInTheDocument();
  });

  it("proposes an underscored name, because the engine's DSL rejects hyphens", async () => {
    // La règle est MESURÉE (urban-workflow 0.2.1, 11/11/2026) : sans ce remplacement,
    // « Demande soumise » proposerait « demande-soumise », refusé par le serveur.
    await openEvents();
    fireEvent.click(await screen.findByText("Declare an event"));

    fill("Label", "Demande soumise");

    expect(screen.getByLabelText("DSL name")).toHaveValue("demande_soumise");
  });

  it("declares the event and opens it, scope included", async () => {
    const calls = await openEvents({
      [`POST ${ROUTE}/declarations?branch=edition`]: { status: 201, body: DEMANDE },
      [`GET ${ROUTE}/shared/demande_soumise?branch=edition`]: {
        status: 200,
        body: { ...DEMANDE, content: BLANK },
      },
      [`GET ${ROUTE}/socle?branch=edition`]: { status: 200, body: SOCLE },
      [`GET ${MODELS}?branch=edition`]: { status: 200, body: [] },
    });
    fireEvent.click(await screen.findByText("Declare an event"));
    fill("Label", "Demande soumise");
    fireEvent.click(screen.getByRole("button", { name: "Declare the event" }));

    await screen.findByRole("heading", { name: "Demande soumise" });
    expect(calls.find((c) => c.key === `POST ${ROUTE}/declarations?branch=edition`)?.body).toEqual(
      { scope: "shared", label: "Demande soumise", slug: "demande_soumise" },
    );
  });

  it("says why a name the DSL would reject is refused", async () => {
    await openEvents({
      [`POST ${ROUTE}/declarations?branch=edition`]: {
        status: 422,
        body: { detail: { field: "name" } },
      },
    });
    fireEvent.click(await screen.findByText("Declare an event"));
    fill("Label", "Demande");
    fill("DSL name", "demande-soumise");
    fireEvent.click(screen.getByRole("button", { name: "Declare the event" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/rejects hyphens/);
  });

  it("shows the base fields ABOVE the business ones, so the derivation is visible", async () => {
    // La demande de Gael du 11/11/2026 : « on ne voit pas que les events dérivent d'un
    // type de base ». Le socle est donc monté dans le MÊME éditeur visuel, verrouillé, et
    // AVANT les champs métier — comme la vue « Événements » du playground d'urban-workflow.
    await openEvents({
      [`GET ${ROUTE}/shared/demande_soumise?branch=edition`]: {
        status: 200,
        body: { ...DEMANDE, content: BLANK },
      },
      [`GET ${ROUTE}/socle?branch=edition`]: { status: 200, body: SOCLE },
      [`GET ${MODELS}?branch=edition`]: { status: 200, body: [] },
    });
    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Demande soumise" }));

    const base = await screen.findByRole("group", { name: "Base fields" });
    // Premier chargement différé de JSONJoy dans ce fichier : plus lent que les suivants.
    expect(await within(base).findByText("ExternalId", {}, { timeout: 10_000 })).toBeInTheDocument();
    expect(within(base).getByText("IntegrationDate")).toBeInTheDocument();
    // Et l'ordre : le socle précède les champs métier dans le document.
    const business = screen.getByRole("group", { name: "Business fields" });
    expect(base.compareDocumentPosition(business)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    // Non modifiable, et l'écran le dit en une phrase qui nomme la dérivation.
    expect(within(base).getByText(/Every event derives from it/)).toBeInTheDocument();
  });

  it("marks in the list an event that carries only the base", async () => {
    await openEvents({ [`GET ${ROUTE}?branch=edition`]: { status: 200, body: [DEMANDE, NU] } });

    const nu = (await screen.findByText("Ping")).closest("li") as HTMLElement;
    const porteuse = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    expect(within(nu).getByText("base only")).toBeInTheDocument();
    expect(within(porteuse).queryByText("base only")).not.toBeInTheDocument();
  });

  it("warns about a business field that collides with the base, before saving", async () => {
    // Le serveur le refuse (propriete_du_socle), mais un refus au moment d'enregistrer
    // arrive après le travail.
    const COLLISION =
      `${BLANK.replace("properties: {}", "properties:")}  ExternalId:\n    type: integer\n`;
    await openEvents({
      [`GET ${ROUTE}/shared/demande_soumise?branch=edition`]: {
        status: 200,
        body: { ...DEMANDE, content: COLLISION },
      },
      [`GET ${ROUTE}/socle?branch=edition`]: { status: 200, body: SOCLE },
      [`GET ${MODELS}?branch=edition`]: { status: 200, body: [] },
    });
    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Demande soumise" }));

    const alerte = await screen.findByRole("alert", {}, { timeout: 10_000 });
    expect(alerte).toHaveTextContent(/ExternalId/);
    expect(alerte).toHaveTextContent(/saving rejects them/);
  });

  it("refuses to show a non-conforming schema without saying which rule broke", async () => {
    await openEvents({
      [`GET ${ROUTE}/shared/demande_soumise?branch=edition`]: {
        status: 200,
        body: { ...DEMANDE, content: BLANK },
      },
      [`GET ${ROUTE}/socle?branch=edition`]: { status: 200, body: SOCLE },
      [`GET ${MODELS}?branch=edition`]: { status: 200, body: [] },
      [`PUT ${ROUTE}/shared/demande_soumise?branch=edition`]: {
        status: 422,
        body: {
          detail: {
            code: "evenement_non_conforme",
            problems: [
              { path: "additionalProperties", code: "schema_ferme", detail: null },
            ],
          },
        },
      },
    });
    const row = (await screen.findByText("Demande soumise")).closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Demande soumise" }));
    const yaml = await screen.findByLabelText("YAML", {}, { timeout: 10_000 });
    fireEvent.change(yaml, {
      target: { value: `${BLANK}additionalProperties: false\n` },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/The event does not follow the grammar/);
    expect(alert).toHaveTextContent(/no real payload would pass/);
  });
});
