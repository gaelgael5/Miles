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
  operation: "/ingest/{source}/{mode}",
  served: true,
  request_schema: SCHEMA,
  model_refusal: null,
  example: [{ code: "code", nom: "nom", postes: 0 }],
};
const FICHIER: Method = {
  ...TABLEAU,
  mode: "fichier",
  path: "/ingest/magasins-import/fichier",
  operation: "/ingest/{source}/fichier",
  served: true,
  // Le gabarit d'un mode fichier est un DOCUMENT : le découpage déclaré par la source
  // désigne un tableau dedans, et c'est le serveur qui en dérive la forme.
  example: { magasins: [{ code: "code", nom: "nom", postes: 0 }] },
};
// Un mode que le paramétrage déclare et que la stack ne sert pas encore. Aucun n'est dans
// ce cas aujourd'hui — les trois sont servis depuis le 04/11/2026 —, mais le drapeau vient
// du serveur, et l'écran doit continuer de l'honorer pour le prochain mode ajouté.
const NON_SERVI: Method = { ...FICHIER, served: false, example: null };
const ESSAI_FICHIER = "POST /api/ingestion/try/magasins-import/fichier";
// Le contrat tel que la route le sert : sa description, ses schémas de sécurité, et une
// opération par gabarit — avec ses en-têtes, son corps et ses réponses.
const CONTRAT = {
  status: 200,
  body: {
    info: { version: "1", description: "Réception, pas collecte : Miles n'appelle personne." },
    components: {
      securitySchemes: {
        cleApiEnEntete: { type: "apiKey", in: "header", name: "X-API-Key", description: "Clé." },
      },
      schemas: { AcknowledgementOut: { type: "object", properties: { id: { type: "string" } } } },
    },
    paths: {
      "/ingest/{source}/{mode}": {
        post: {
          description: "Dépose un lot d'objets.",
          parameters: [
            { name: "source", in: "path", required: true },
            {
              name: "Idempotency-Key",
              in: "header",
              required: false,
              description: "Rend un rejeu sûr.",
            },
          ],
          requestBody: {
            required: true,
            content: { "application/json": { schema: { type: "object" } } },
          },
          responses: {
            "201": {
              description: "Lot reçu et traité.",
              content: {
                "application/json": {
                  schema: { $ref: "#/components/schemas/AcknowledgementOut" },
                },
              },
            },
            "401": { description: "authentification_requise." },
          },
        },
      },
      "/ingest/{source}/fichier": {
        post: {
          description: "Dépose un document.",
          parameters: [{ name: "source", in: "path", required: true }],
          requestBody: {
            required: true,
            content: {
              "application/json": { schema: { type: "object" } },
              "application/octet-stream": { schema: { type: "string", format: "binary" } },
            },
          },
          responses: { "202": { description: "Document pris en charge." } },
        },
      },
    },
  },
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
      <IngestionMethods source="magasins-import" />
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
    // Le mode n'est pas répété à côté du chemin : il EST son dernier segment.
    expect(within(bloc).getByRole("heading").textContent).toBe(
      "POST /ingest/magasins-import/tableau",
    );
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

  it("montre un mode non servi sans bouton, et dit pourquoi", async () => {
    monte(methodes(NON_SERVI));

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

  it("montre la SIGNATURE de chaque méthode, lue du contrat publié", async () => {
    // La page de contrat : en-têtes, types de contenu, réponses et leurs formes. C'est ce
    // qui permet de préparer une intégration SANS essayer (Gael, 04/11/2026).
    monte({ ...methodes(TABLEAU), "GET /api/ingestion/contract": CONTRAT });

    const bloc = (await screen.findByText(/\/ingest\/magasins-import\/tableau/)).closest(
      "li",
    ) as HTMLElement;
    // Une LIGNE par chose — en-têtes, corps, codes de réponse : la page se parcourt.
    expect(within(bloc).getByText(/Idempotency-Key \(optional\)/)).toBeInTheDocument();
    expect(within(bloc).getByText("Body", { selector: "span.caption" }).parentElement?.textContent).toContain(
      "application/json",
    );
    expect(within(bloc).getByText("Responses", { selector: "span.caption" }).parentElement
        ?.textContent).toContain(
      "201 · 401",
    );
    // Et ce que chaque réponse dit, derrière un repli.
    expect(within(bloc).getByText(/Lot reçu et traité/)).toBeInTheDocument();
  });

  it("montre les réponses de la MÉTHODE, et non celles d'une autre", async () => {
    // Le mode fichier rend 202 et un accusé sans compte-rendu ; les deux autres rendent
    // 201 et le sort de chaque objet. Les mélanger ferait promettre à l'un ce que l'autre
    // tient.
    monte({ ...methodes(TABLEAU, FICHIER), "GET /api/ingestion/contract": CONTRAT });

    const fichier = (await screen.findByText(/\/ingest\/magasins-import\/fichier/)).closest(
      "li",
    ) as HTMLElement;
    // Sa ligne de réponses ne porte QUE les siennes : 202, et pas le 201 du mode tableau.
    const codes = within(fichier).getByText("Responses", { selector: "span.caption" })
      .parentElement as HTMLElement;
    expect(codes.textContent).toBe("Responses 202");
    expect(within(fichier).getByText(/Document pris en charge/)).toBeInTheDocument();
    // Et son corps propre : un flux d'octets est admis en plus du JSON. Lu sur la LIGNE
    // du corps — le schéma déclaré, derrière le repli des schémas, porte le même texte.
    const corps = within(fichier).getByText("Body", { selector: "span.caption" })
      .parentElement as HTMLElement;
    expect(corps.textContent).toContain("application/octet-stream");
  });

  it("montre le schéma du MODÈLE d'entrée, celui que la validation emploie", async () => {
    monte({ ...methodes(TABLEAU), "GET /api/ingestion/contract": CONTRAT });

    const bloc = (await screen.findByText(/\/ingest\/magasins-import\/tableau/)).closest(
      "li",
    ) as HTMLElement;

    expect(within(bloc).getByText(/Input model pudo\/magasin/i)).toBeInTheDocument();
  });

  it("dit comment s'authentifier, et ce que le contrat garantit, avant tout appel", async () => {
    // La partie « connexions en amont » : elle se prépare sans accès et sans essai.
    monte({ ...methodes(TABLEAU), "GET /api/ingestion/contract": CONTRAT });

    expect(await screen.findByText(/Published contract, version 1/i)).toBeInTheDocument();
    expect(screen.getByText("X-API-Key")).toBeInTheDocument();
    // En PROSE, et pas seulement dans la spécification brute dépliable : c'est le texte
    // qu'on lit avant de brancher quoi que ce soit.
    const dit = screen.getAllByText(/Réception, pas collecte/);
    expect(dit.some((noeud) => noeud.tagName === "P")).toBe(true);
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

describe("la troisième méthode, le mode fichier", () => {
  it("offre un CHOIX DE FICHIER, et non une zone de texte", async () => {
    monte(methodes(FICHIER));

    expect(await screen.findByLabelText(/Document to deposit/i)).toHaveAttribute("type", "file");
    // Pas de corps à saisir : ce qu'on dépose est un document, pas un lot tapé à la main.
    expect(screen.queryByLabelText(/Body to deposit/i)).not.toBeInTheDocument();
    // Et la mention « pas encore servie » a disparu, puisque le mode l'est.
    expect(screen.queryByText(/is not served yet/i)).not.toBeInTheDocument();
  });

  it("montre la forme ATTENDUE DU DOCUMENT, découpage compris", async () => {
    monte(methodes(FICHIER));

    // Le gabarit est celui du document — le tableau est là où le découpage le cherche —,
    // et non celui d'un objet seul, qui n'aurait pas dit quoi déposer.
    expect(await screen.findByText(/"magasins":/)).toBeInTheDocument();
  });

  it("ne dépose pas tant qu'aucun fichier n'est choisi", async () => {
    monte(methodes(FICHIER));

    expect(await screen.findByRole("button", { name: "Deposit" })).toBeDisabled();
  });

  it("relaie le fichier choisi et montre l'acquittement de prise en charge", async () => {
    const calls = monte({
      ...methodes(FICHIER),
      [ESSAI_FICHIER]: {
        status: 200,
        body: {
          status: 202,
          body: { id: "b".repeat(32), state: "en_file", report: null, replayed: false },
        },
      },
    });
    const champ = (await screen.findByLabelText(/Document to deposit/i)) as HTMLInputElement;
    const document = new File(['{"magasins": [{"code": "M-1"}]}'], "magasins.json", {
      type: "application/json",
    });

    fireEvent.change(champ, { target: { files: [document] } });
    fireEvent.click(screen.getByRole("button", { name: "Deposit" }));

    expect(await screen.findByText(/HTTP response 202/)).toBeInTheDocument();
    // L'accusé ne porte PAS de compte-rendu : l'import se déroule après, et l'écran ne
    // doit pas faire lire un 202 comme un import sans objet.
    expect(await screen.findByText(/"state": "en_file"/)).toBeInTheDocument();
    expect(calls.some((appel) => appel.key === ESSAI_FICHIER)).toBe(true);
  });
});
