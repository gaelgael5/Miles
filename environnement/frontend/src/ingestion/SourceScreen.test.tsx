import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { i18n } from "@miles/socle-web";
import { type Routes, mockApi } from "@miles/socle-web/testing";

import "../i18n/i18n";
import type { Call, Method } from "../api/ingestion";
import { SourceScreen } from "./SourceScreen";

const TABLEAU: Method = {
  source: "comptes-pudo",
  storage: "accounts",
  entry_model: "pudo/accounts",
  mode: "tableau",
  path: "/ingest/comptes-pudo/tableau",
  operation: "/ingest/{source}/{mode}",
  served: true,
  request_schema: { type: "object" },
  model_refusal: null,
  example: [{ code: "code" }],
};
// Une méthode d'une AUTRE source : c'est elle qui rend le filtrage mesurable.
const AUTRE: Method = {
  ...TABLEAU,
  source: "sites-pudo",
  storage: "sites",
  path: "/ingest/sites-pudo/tableau",
};
const APPEL: Call = {
  id: "a".repeat(32),
  source: "comptes-pudo",
  mode: "tableau",
  entry_model: "pudo/accounts",
  object_count: 42,
  size_bytes: 1337,
  version_number: 4,
  key_label: "Transporteur",
  key_prefix: "mlk_kkkkkkkk",
  received_at: "2026-11-02T09:30:00Z",
  state: "recu",
};

// Le contrat TEL QUE LE SERVEUR LE REND pour cette source : adresse réelle, plus aucun
// gabarit. La spécialisation elle-même est éprouvée côté serveur (`test_source_contract`)
// — un jeu d'essai qui porterait encore le gabarit décrirait un document que plus
// personne ne sert.
const CONTRAT = {
  info: { version: "1", description: "Réception, pas collecte : Miles n'appelle personne." },
  components: {
    securitySchemes: {
      cleApiEnEntete: { type: "apiKey", in: "header", name: "X-API-Key", description: "Clé." },
    },
  },
  paths: {
    "/ingest/comptes-pudo/tableau": {
      post: {
        description: "Dépose un lot d'objets.",
        parameters: [{ name: "Idempotency-Key", in: "header", required: false }],
        requestBody: { required: true, content: { "application/json": { schema: {} } } },
        responses: { "201": { description: "Lot reçu et traité." } },
      },
    },
  },
};

const SURFACE: Routes = {
  "GET /api/ingestion/methods": { status: 200, body: { methods: [TABLEAU, AUTRE] } },
  // Le contrat de la source, déjà spécialisé PAR LE SERVEUR : c'est le document que
  // l'écran lit et que l'intégrateur télécharge, à la même adresse.
  "GET /api/ingestion/contract/comptes-pudo": { status: 200, body: CONTRAT },
  "GET /api/ingestion/contract/sites-pudo-absente": { status: 404, body: { detail: "source_inconnue" } },
  "GET /api/ingestion/calls": {
    status: 200,
    body: { calls: [APPEL], total: 1, page: 1, page_size: 50, sources: ["comptes-pudo"] },
  },
};

function monte(routes: Routes = {}, source = "comptes-pudo") {
  const calls = mockApi({ ...SURFACE, ...routes });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const vue = render(
    <QueryClientProvider client={client}>
      <SourceScreen source={source} />
    </QueryClientProvider>,
  );
  // Le client est rendu pour les essais qui RÉAFFICHENT la page sur une autre source :
  // en reprendre un neuf viderait le cache, et la page repartirait de zéro pour une
  // raison étrangère à ce qu'ils mesurent.
  const revoir = (autre: string) =>
    vue.rerender(
      <QueryClientProvider client={client}>
        <SourceScreen source={autre} />
      </QueryClientProvider>,
    );
  return { calls, revoir };
}

/** L'onglet du journal, ouvert : les deux tiers des essais commencent par là. */
async function ouvreLeJournal() {
  fireEvent.click(await screen.findByRole("tab", { name: "Call log" }));
}

describe("la page d'une source d'ingestion", () => {
  it("s'ouvre sur le contrat de CETTE source, donné à un visualiseur Swagger", async () => {
    monte();

    // Le document donné au visualiseur porte l'adresse RÉELLE de la source, et non le
    // gabarit du contrat publié : c'est elle qu'un partenaire appelle.
    const donne = JSON.parse((await screen.findByTestId("swagger-spec")).textContent ?? "{}");
    expect(Object.keys(donne.paths)).toEqual(["/ingest/comptes-pudo/tableau"]);
    expect(screen.getByRole("tab", { name: "Contract" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("donne l'adresse publique du contrat, et de quoi le télécharger", async () => {
    // Un contrat n'est utile que si l'intégrateur peut l'ouvrir : la même adresse que
    // l'écran lit, pour qu'on ne publie pas autre chose que ce qu'on regarde.
    monte();

    const bloc = within(await screen.findByRole("region", { name: "Public contract address" }));
    const lien = bloc.getByRole("link", { name: "Download" });
    expect(lien).toHaveAttribute("href", expect.stringContaining("/api/ingestion/contract/comptes-pudo"));
    expect(lien).toHaveAttribute("download", "comptes-pudo.openapi.json");
    expect(bloc.getByText(/opens without an account/)).toBeInTheDocument();
  });

  it("dit qu'une source sans entrée dans la version servie n'a aucune méthode", async () => {
    monte({}, "sites-pudo-absente");

    expect(await screen.findByText(/declares no entry for this source/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("dit que le contrat publié n'a pas pu être lu, sans rendre un contrat amputé", async () => {
    // Un contrat partiel se lirait « cette source n'expose que ça », et c'est pire que
    // pas de contrat du tout.
    monte({ "GET /api/ingestion/contract/comptes-pudo": { status: 500, body: {} } });

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not be read/i);
    expect(screen.queryByTestId("swagger-spec")).not.toBeInTheDocument();
  });

  it("essaie les méthodes de la source dans l'onglet voisin, pas dans le contrat", async () => {
    // Le « Try it out » de Swagger partirait sans clé d'API : l'essai qui dépose pour de
    // vrai est à part, avec la clé du back-office.
    monte();
    fireEvent.click(await screen.findByRole("tab", { name: "Trial" }));

    expect(await screen.findByText(/\/ingest\/comptes-pudo\/tableau/)).toBeInTheDocument();
    // On équipe un partenaire sur UNE source : les adresses des autres n'ont rien à
    // faire sous ses yeux.
    expect(screen.queryByText(/\/ingest\/sites-pudo\/tableau/)).not.toBeInTheDocument();
  });

  it("ouvre le journal de la source dans l'autre onglet", async () => {
    const { calls } = monte();

    await ouvreLeJournal();

    expect(await screen.findByText("1 call(s)")).toBeInTheDocument();
    const journal = within(screen.getByRole("region", { name: "Recent calls" }));
    expect(journal.getByText(/42 object\(s\)/)).toBeInTheDocument();
    expect(journal.getByText(/1337 bytes/)).toBeInTheDocument();
    // Le préfixe de la clé, jamais sa valeur.
    expect(journal.getByText(/by Transporteur \(mlk_kkkkkkkk\)/)).toBeInTheDocument();
    // Le journal est borné à la source de la page : sans ce paramètre, la page montrerait
    // les dépôts de tout le monde sous le nom d'un seul partenaire.
    await waitFor(() =>
      expect(calls.map((appel) => appel.key)).toContain(
        "GET /api/ingestion/calls?page=1&source=comptes-pudo",
      ),
    );
  });

  it("n'offre aucun filtre de source dans le journal : le menu la désigne", async () => {
    monte();

    await ouvreLeJournal();
    await screen.findByText("1 call(s)");

    // Deux façons de choisir la même chose auraient divergé : la source du filtre
    // n'aurait pas été celle que le menu montre comme courante.
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("montre un onglet à la fois, jamais deux", async () => {
    monte();

    await ouvreLeJournal();

    expect(await screen.findByText("1 call(s)")).toBeInTheDocument();
    expect(screen.queryByTestId("swagger-spec")).not.toBeInTheDocument();
  });

  it("change d'onglet aux flèches, et ne garde qu'une entrée au clavier dans la barre", async () => {
    monte();
    const contrat = await screen.findByRole("tab", { name: "Contract" });

    fireEvent.keyDown(contrat, { key: "ArrowRight" });

    const essai = screen.getByRole("tab", { name: "Trial" });
    expect(essai).toHaveAttribute("aria-selected", "true");
    expect(essai).toHaveAttribute("tabindex", "0");
    // L'onglet inactif sort de l'ordre de tabulation : sinon la tabulation traverse la
    // barre avant d'atteindre les formulaires d'essai.
    expect(contrat).toHaveAttribute("tabindex", "-1");
  });

  it("écrit la date du journal dans la culture de l'INTERFACE, pas celle du navigateur", async () => {
    // Forcé en français : les tests du dépôt tournent en en-US, où le défaut d'origine
    // — `toLocaleString()` sans culture — était rigoureusement invisible (bug 4f53012d).
    await i18n.changeLanguage("fr-FR");
    try {
      monte();
      fireEvent.click(await screen.findByRole("tab", { name: "Journal" }));

      expect(await screen.findByText("1 appel(s)")).toBeInTheDocument();
      const journal = within(screen.getByRole("region", { name: "Derniers appels" }));
      // 02/11, et non 11/02 : l'appel a été reçu le 2 novembre. Sur ce journal la date
      // EST l'information de la colonne, et un lecteur français y lisait le 11 février.
      expect(journal.getByText(/^02\/11\/2026/)).toBeInTheDocument();
    } finally {
      // Dans `act` : l'écran est encore monté, et le retour à en-US le fait rendre.
      await act(() => i18n.changeLanguage("en-US"));
    }
  });

  it("dit « aucun appel » sans en faire une erreur", async () => {
    monte({
      "GET /api/ingestion/calls": {
        status: 200,
        body: { calls: [], total: 0, page: 1, page_size: 50, sources: ["comptes-pudo"] },
      },
    });

    await ouvreLeJournal();

    expect(await screen.findByText("No call received.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("distingue une lecture en échec d'un journal vide", async () => {
    // Les confondre ferait conclure que tout va bien au pire moment pour le conclure.
    monte({ "GET /api/ingestion/calls": { status: 500, body: {} } });

    await ouvreLeJournal();

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be read");
    expect(screen.queryByText("No call received.")).not.toBeInTheDocument();
  });

  it("revient à la première page quand on passe à une autre source", async () => {
    // Rester en page 3 d'une source qui n'en a qu'une afficherait un vide qu'on prendrait
    // pour « ce partenaire n'a rien déposé ». Éprouvé en allant d'abord à la page 2 :
    // sans ce détour, l'assertion « page 1 » serait vraie sans rien prouver.
    const { revoir } = monte({
      "GET /api/ingestion/calls": {
        status: 200,
        body: { calls: [APPEL], total: 120, page: 1, page_size: 50, sources: ["comptes-pudo"] },
      },
    });
    await ouvreLeJournal();
    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();

    revoir("sites-pudo");

    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
  });
});
