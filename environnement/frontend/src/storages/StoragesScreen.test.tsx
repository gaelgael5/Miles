import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { type Routes, mockApi } from "@miles/socle-web/testing";

import "../i18n/i18n";
import type { Storage } from "../api/storages";
import { StoragesScreen } from "./StoragesScreen";

const ACCOUNTS: Storage = {
  name: "accounts",
  label: "Accounts",
  model: "pudo/accounts",
  schema_name: "pudo",
  table_name: "accounts",
  keys: ["$.AccountId"],
  projections: [
    { column: "contact_phone", path: "$.Contact.Phone", kind: "string", sql_type: "text" },
  ],
  indexes: [{ name: "tel", columns: ["contact_phone"] }],
  applied_at: "2026-11-02T07:08:26Z",
  version_number: 1,
  refusal: null,
  refusal_detail: null,
};

function monte(routes: Routes) {
  const calls = mockApi(routes);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StoragesScreen />
    </QueryClientProvider>,
  );
  return calls;
}

describe("la liste des espaces de stockage", () => {
  it("liste les espaces avec leur modèle et leur table", async () => {
    monte({ "GET /api/storages": { status: 200, body: [ACCOUNTS] } });

    expect(await screen.findByText("Accounts")).toBeInTheDocument();
    expect(screen.getByText("pudo/accounts")).toBeInTheDocument();
    expect(screen.getByText("pudo.accounts")).toBeInTheDocument();
  });

  it("ne cherche RIEN depuis la liste : les objets sont sur la page de l'espace", async () => {
    // La garde du découpage du 04/11/2026. Tenir la recherche ici faisait lire les
    // colonnes d'un espace en cherchant dans un autre.
    const calls = monte({ "GET /api/storages": { status: 200, body: [ACCOUNTS] } });

    expect(await screen.findByText("Accounts")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Search filters" })).not.toBeInTheDocument();
    expect(calls.map((c) => c.key)).toEqual(["GET /api/storages"]);
  });

  it("dit ce qu'il n'y a pas, plutôt que de rendre un écran vide", async () => {
    monte({ "GET /api/storages": { status: 200, body: [] } });

    expect(
      await screen.findByText("The served version declares no storage space."),
    ).toBeInTheDocument();
  });

  it("montre un espace refusé dans la même liste, et dit pourquoi", async () => {
    // L'écarter de la liste le rendrait invisible : on chercherait une déclaration
    // absente alors qu'elle est là, et fautive.
    monte({
      "GET /api/storages": {
        status: 200,
        body: [
          {
            ...ACCOUNTS,
            applied_at: null,
            version_number: null,
            refusal: "propriete_inconnue",
            refusal_detail: "$.PhoneNumber",
          },
        ],
      },
    });

    expect(
      await screen.findByText(/An indexed property does not exist in the model/),
    ).toBeInTheDocument();
    expect(screen.getByText("$.PhoneNumber")).toBeInTheDocument();
  });

  it("distingue une table pas encore posée d'une table posée", async () => {
    monte({
      "GET /api/storages": {
        status: 200,
        body: [{ ...ACCOUNTS, applied_at: null, version_number: null }],
      },
    });

    expect(await screen.findByText(/table is not created yet/)).toBeInTheDocument();
  });

  it("dit que les espaces n'ont pas pu être lus", async () => {
    monte({ "GET /api/storages": { status: 500, body: {} } });

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be read");
  });
});
