import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { type Routes, mockApi } from "@miles/socle-web/testing";

import "../i18n/i18n";
import type { Method } from "../api/ingestion";
import { IngestionMethods } from "./IngestionMethods";

const SCHEMA = {
  type: "object",
  required: ["code", "nom"],
  properties: { code: { type: "string" }, nom: { type: "string" }, postes: { type: "integer" } },
};
const TABLEAU: Method = {
  source: "magasins-import",
  storage: "magasins",
  entry_model: "pudo/magasin",
  mode: "tableau",
  path: "/ingest/magasins-import/tableau",
  served: true,
  request_schema: SCHEMA,
  model_refusal: null,
  example: [{ code: "code", nom: "nom", postes: 0 }],
};
const FICHIER: Method = {
  ...TABLEAU,
  mode: "fichier",
  path: "/ingest/magasins-import/fichier",
  served: false,
  example: null,
};
const ESSAI = "POST /api/ingestion/try/magasins-import/tableau";
const ACCUSE = {
  id: "a".repeat(32),
  source: "magasins-import",
  mode: "tableau",
  object_count: 1,
  state: "traite",
  replayed: false,
  report: {
    received: 1,
    written: 1,
    unchanged: 0,
    rejected: 0,
    objects: [{ position: 0, outcome: "ecrit", key: '["M-1"]', reason: null, detail: null }],
    anomalies: [],
  },
};

function monte(routes: Routes) {
  const calls = mockApi({
    "GET /api/ingestion/contract": { status: 200, body: {} },
    ...routes,
  });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <IngestionMethods />
    </QueryClientProvider>,
  );
  return calls;
}

function methodes(...liste: Method[]): Routes {
  return { "GET /api/ingestion/methods": { status: 200, body: { methods: liste } } };
}

describe("les méthodes du service d'ingestion", () => {
  it("donne un bloc par méthode, avec son adresse et ce qu'elle alimente", async () => {
    monte(methodes(TABLEAU));

    const bloc = (await screen.findByText(/\/ingest\/magasins-import\/tableau/)).closest(
      "li",
    ) as HTMLElement;
    expect(within(bloc).getByText("tableau")).toBeInTheDocument();
    expect(within(bloc).getByText("pudo/magasin")).toBeInTheDocument();
    expect(within(bloc).getByText("magasins")).toBeInTheDocument();
  });

  it("dit qu'il n'y a aucune méthode, sans en faire une panne", async () => {
    monte(methodes());

    // L'état normal d'une stack sans version servie, et non une erreur : pas d'alerte.
    expect(await screen.findByText(/no method/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("sème le corps avec le gabarit du modèle, et le laisse modifier", async () => {
    monte(methodes(TABLEAU));

    const corps = (await screen.findByLabelText(/Body to deposit/i)) as HTMLTextAreaElement;

    expect(JSON.parse(corps.value)).toEqual([{ code: "code", nom: "nom", postes: 0 }]);
    fireEvent.change(corps, { target: { value: '[{"code":"M-9"}]' } });
    expect(corps.value).toBe('[{"code":"M-9"}]');
  });

  it("NOMME un modèle que la version servie ne porte pas, au lieu d'un corps vide", async () => {
    // Un corps vide se lirait « cette méthode n'attend rien » : la vraie information est
    // qu'une pièce manque au paramétrage servi.
    monte(
      methodes({ ...TABLEAU, request_schema: null, model_refusal: "modele_absent", example: null }),
    );

    expect(await screen.findByText(/does not carry the input model pudo\/magasin/i)).toBeVisible();
    expect(screen.queryByLabelText(/Body to deposit/i)).not.toBeInTheDocument();
  });

  it("dépose pour de vrai et montre la réponse du point d'entrée", async () => {
    const calls = monte({
      ...methodes(TABLEAU),
      [ESSAI]: { status: 200, body: { status: 201, body: ACCUSE } },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Deposit" }));

    expect(await screen.findByText(/HTTP response 201/)).toBeInTheDocument();
    // Le compte-rendu objet par objet arrive jusqu'à l'écran, tel quel.
    expect(await screen.findByText(/"outcome": "ecrit"/)).toBeInTheDocument();
    // Et le corps saisi est bien parti sur l'adresse de CETTE méthode.
    expect(calls.some((appel) => appel.key === ESSAI)).toBe(true);
  });

  it("montre un lot entièrement rejeté comme un refus du dépôt, pas comme une panne", async () => {
    const rejete = { ...ACCUSE, state: "rejete", report: { ...ACCUSE.report, written: 0, rejected: 1 } };
    monte({
      ...methodes(TABLEAU),
      [ESSAI]: { status: 200, body: { status: 422, body: rejete } },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Deposit" }));

    const statut = await screen.findByText(/HTTP response 422/);
    // En alerte, parce que le dépôt n'a rien écrit — et non en « l'écran a échoué ».
    expect(statut.className).toContain("alert");
    expect(screen.getByText(/"state": "rejete"/)).toBeInTheDocument();
  });

  it("relaie le refus du point d'entrée sur un corps que l'administrateur a mal écrit", async () => {
    monte({
      ...methodes(TABLEAU),
      [ESSAI]: {
        status: 200,
        body: {
          status: 400,
          body: { detail: { code: "json_invalide", detail: "ligne 1 colonne 12" } },
        },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Deposit" }));

    expect(await screen.findByText(/HTTP response 400/)).toBeInTheDocument();
    // Le code ET la position : l'écran ne corrige pas la saisie, il dit où elle casse.
    expect(screen.getByText(/ligne 1 colonne 12/)).toBeInTheDocument();
  });

  it("montre la troisième méthode sans bouton, et dit qu'elle n'est pas servie", async () => {
    monte(methodes(FICHIER));

    expect(await screen.findByText(/is not served yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deposit" })).not.toBeInTheDocument();
    // Sa place est gardée : l'adresse reste lisible pour qui prépare son intégration.
    expect(screen.getByText(/\/ingest\/magasins-import\/fichier/)).toBeInTheDocument();
  });

  it("dit que la clé du back-office a été révoquée, et offre d'en réémettre une", async () => {
    const calls = monte({
      ...methodes(TABLEAU),
      [ESSAI]: {
        status: 409,
        body: { detail: { code: "cle_du_back_office_revoquee", detail: null } },
      },
      "POST /api/ingestion/self-key": { status: 201, body: {} },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Deposit" }));
    const dit = await screen.findByText(/has been revoked/i);
    fireEvent.click(screen.getByRole("button", { name: /Issue a new back-office key/i }));

    expect(dit).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Key issued" })).toBeDisabled();
    expect(calls.some((appel) => appel.key === "POST /api/ingestion/self-key")).toBe(true);
  });

  it("affiche les réponses déclarées par le contrat publié, lues et non recopiées", async () => {
    monte({
      ...methodes(TABLEAU),
      "GET /api/ingestion/contract": {
        status: 200,
        body: {
          paths: {
            "/ingest/{source}/{mode}": {
              post: {
                responses: {
                  "201": { description: "Lot reçu et traité." },
                  "401": { description: "authentification_requise." },
                },
              },
            },
          },
        },
      },
    });

    expect(await screen.findByText("401")).toBeInTheDocument();
    expect(screen.getByText(/authentification_requise/)).toBeInTheDocument();
    expect(screen.getByText("201")).toBeInTheDocument();
  });

  it("reste muet sur le contrat quand il n'a pas pu être lu", async () => {
    // Un complément de lecture : son absence n'empêche ni de lire les méthodes ni d'en
    // essayer une, et une alerte ici ferait croire que le service va mal.
    monte({ ...methodes(TABLEAU), "GET /api/ingestion/contract": { status: 500, body: {} } });

    expect(await screen.findByLabelText(/Body to deposit/i)).toBeInTheDocument();
    expect(screen.queryByText(/Responses declared/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("distingue une lecture des méthodes en échec d'une absence de méthode", async () => {
    monte({ "GET /api/ingestion/methods": { status: 500, body: {} } });

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be read/i);
    expect(screen.queryByText(/no method/i)).not.toBeInTheDocument();
  });
});
