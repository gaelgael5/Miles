import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";

import { type Routes, mockApi } from "@miles/socle-web/testing";

import "../i18n/i18n";
import type { Method } from "../api/ingestion";
import { ContractCurl, curlFor } from "./ContractCurl";

const FICHIER: Method = {
  source: "comptes-pudo",
  storage: "accounts",
  entry_model: "pudo/accounts",
  mode: "fichier",
  path: "/ingest/comptes-pudo/fichier",
  operation: "/ingest/{source}/{mode}",
  served: true,
  request_schema: { type: "object" },
  model_refusal: null,
  example: null,
};
const ELEMENT: Method = {
  ...FICHIER,
  mode: "element",
  path: "/ingest/comptes-pudo/element",
  example: { code: "FR-1", libelle: "Épicerie du Pont" },
};

function monte(methods: Method[]) {
  const routes: Routes = {
    "GET /api/ingestion/methods": { status: 200, body: { methods } },
  };
  mockApi(routes);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
    <ContractCurl source="comptes-pudo" />
    </QueryClientProvider>,
  );
}

describe("ContractCurl", () => {
  it("rend la commande du mode fichier, qui envoie un document depuis le disque", async () => {
    monte([FICHIER]);
    await waitFor(() => expect(screen.getByText(/curl -X POST/)).toBeInTheDocument());
    const commande = screen.getByText(/curl -X POST/).textContent ?? "";
    expect(commande).toContain("/ingest/comptes-pudo/fichier");
    expect(commande).toContain("--data-binary '@document.json'");
    // Le corps d'un gros fichier n'a rien à faire sur une ligne de commande.
    expect(commande).not.toContain("--data '");
  });

  it("rend la commande d'un mode synchrone avec le gabarit publié", async () => {
    monte([ELEMENT]);
    await waitFor(() => expect(screen.getByText(/curl -X POST/)).toBeInTheDocument());
    const commande = screen.getByText(/curl -X POST/).textContent ?? "";
    expect(commande).toContain("/ingest/comptes-pudo/element");
    expect(commande).toContain("X-API-Key: VOTRE_CLE_API");
  });

  it("n'offre pas de commande pour un mode que la stack ne sert pas", async () => {
    monte([{ ...FICHIER, served: false }]);
    await waitFor(() => expect(screen.queryByText(/curl -X POST/)).not.toBeInTheDocument());
  });

  it("ne montre rien quand la source n'expose aucune méthode servie", async () => {
    monte([{ ...FICHIER, source: "une-autre" }]);
    await waitFor(() => expect(screen.queryByText(/curl -X POST/)).not.toBeInTheDocument());
  });
});

describe("curlFor", () => {
  it("échappe l'apostrophe du gabarit pour que la commande reste valide", () => {
    // « Épicerie d'Or » : sans échappement, la chaîne du shell se referme au milieu du
    // corps, et le terminal attend une suite qui ne vient jamais. C'est le cas qui arrive
    // dès qu'un libellé français entre dans un gabarit.
    const commande = curlFor({ ...ELEMENT, example: { libelle: "Épicerie d'Or" } });

    expect(commande).toContain(`'\\''`);
    // Le corps reste un JSON lisible une fois le shell passé dessus : on simule ce que
    // le shell en ferait — refermer, insérer une apostrophe littérale, rouvrir.
    const corps = commande.split("--data ")[1] ?? "";
    const rendu = corps.slice(1, -1).split(`'\\''`).join("'");
    expect(JSON.parse(rendu)).toEqual({ libelle: "Épicerie d'Or" });
  });

  it("rend un corps vide plutôt qu'aucun corps quand le gabarit manque", () => {
    expect(curlFor({ ...ELEMENT, example: null })).toContain("--data '{}'");
  });
});
