import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
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
    { column: "postes", path: "$.Postes", kind: "integer", sql_type: "bigint" },
  ],
  indexes: [
    { name: "tel", columns: ["contact_phone"] },
    { name: "taille", columns: ["postes"] },
  ],
  applied_at: "2026-11-02T07:08:26Z",
  version_number: 1,
  refusal: null,
  refusal_detail: null,
};
const OBJET = {
  cle: "A-1",
  objet: { AccountId: "A-1", Postes: 3 },
  vu_le: "2026-11-02T07:10:00Z",
  modifie_le: "2026-11-02T07:10:00Z",
  origine: "import",
  columns: { contact_phone: "0102030405", postes: 3 },
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

const UNE_LISTE: Routes = { "GET /api/storages": { status: 200, body: [ACCOUNTS] } };
const UNE_PAGE: Routes = {
  ...UNE_LISTE,
  "GET /api/storages/accounts/objects": {
    status: 200,
    body: { objects: [OBJET], total: 1, page: 1, page_size: 50 },
  },
};

describe("les espaces de stockage de la version servie", () => {
  it("liste les espaces avec leur modèle et leur table", async () => {
    monte(UNE_LISTE);

    expect(await screen.findByRole("button", { name: "Accounts" })).toBeInTheDocument();
    expect(screen.getByText("pudo/accounts")).toBeInTheDocument();
    expect(screen.getByText("pudo.accounts")).toBeInTheDocument();
  });

  it("dit ce qu'il n'y a pas, plutôt que de rendre un écran vide", async () => {
    monte({ "GET /api/storages": { status: 200, body: [] } });

    expect(
      await screen.findByText("The served version declares no storage space."),
    ).toBeInTheDocument();
  });

  it("montre la clé fonctionnelle et les index sous leur chemin DÉCLARÉ", async () => {
    // Pas « contact_phone » : c'est sous « $.Contact.Phone » que la personne a choisi la
    // propriété dans le portail, et le nom de colonne dérivé ne lui dirait pas lequel de
    // ses index elle regarde.
    monte(UNE_LISTE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));

    expect(screen.getByText(/Functional key: \$\.AccountId/)).toBeInTheDocument();
    expect(screen.getByText(/\$\.Contact\.Phone/)).toBeInTheDocument();
  });

  it("n'offre en filtre que la clé fonctionnelle et les colonnes des index déclarés", async () => {
    // La même règle que l'arbre des propriétés du portail : on ne propose que ce qui
    // marche, plutôt que de laisser découvrir le refus après coup.
    monte(UNE_PAGE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));
    const filtres = within(screen.getByRole("form", { name: "Search filters" }));
    fireEvent.click(filtres.getByRole("button", { name: "Add a filter" }));

    // La liste EXACTE, valeurs comprises : compter les libellés ne discriminait pas —
    // une propriété offerte à tort mais sans chemin déclaré passait au travers.
    const proposees = within(
      within(screen.getByRole("form", { name: "Search filters" })).getByLabelText("Property"),
    )
      .getAllByRole<HTMLOptionElement>("option")
      .filter((option) => option.value !== "")
      .map((option) => [option.value, option.textContent]);
    expect(proposees).toEqual([
      ["cle", "$.AccountId"],
      ["contact_phone", "$.Contact.Phone"],
      ["postes", "$.Postes"],
    ]);
  });

  it("envoie le critère au serveur dans la forme qu'il attend", async () => {
    const calls = monte(UNE_PAGE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));
    const form = () => within(screen.getByRole("form", { name: "Search filters" }));
    fireEvent.click(form().getByRole("button", { name: "Add a filter" }));
    fireEvent.change(form().getByLabelText("Property"), { target: { value: "contact_phone" } });
    fireEvent.change(form().getByLabelText("Comparison"), { target: { value: "prefixe" } });
    fireEvent.change(form().getByLabelText("Value"), { target: { value: "0102" } });

    expect(await screen.findByText("A-1")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toContain(
      "GET /api/storages/accounts/objects?f=contact_phone%3Aprefixe%3A0102&page=1",
    );
  });

  it("n'interroge pas le serveur sur un critère incomplet", async () => {
    // Un filtre qu'on vient d'ajouter n'a ni propriété ni valeur : l'envoyer ferait
    // refuser la recherche, et afficher une erreur que personne n'a provoquée.
    const calls = monte(UNE_PAGE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));
    expect(await screen.findByText("A-1")).toBeInTheDocument();
    const avant = calls.filter((c) => c.key.includes("/objects")).length;
    fireEvent.click(
      within(screen.getByRole("form", { name: "Search filters" })).getByRole("button", {
        name: "Add a filter",
      }),
    );

    expect(calls.filter((c) => c.key.includes("/objects"))).toHaveLength(avant);
  });

  it("rend l'objet, ses colonnes projetées et ses deux dates", async () => {
    monte(UNE_PAGE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));

    expect(await screen.findByText("1 object found")).toBeInTheDocument();
    expect(screen.getByText("A-1")).toBeInTheDocument();
    // La valeur de la colonne projetée est affichée : c'est elle qui dit pourquoi cet
    // objet est dans le résultat.
    expect(screen.getByText("0102030405")).toBeInTheDocument();
    expect(screen.getByText(/seen on/)).toBeInTheDocument();
    expect(screen.getByText(/changed on/)).toBeInTheDocument();
  });

  it("dit « aucun objet » sans en faire une erreur", async () => {
    monte({
      ...UNE_LISTE,
      "GET /api/storages/accounts/objects": {
        status: 200,
        body: { objects: [], total: 0, page: 1, page_size: 50 },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));

    expect(await screen.findByText("No object matches.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("nomme la propriété quand le serveur refuse le critère", async () => {
    monte({
      ...UNE_LISTE,
      "GET /api/storages/accounts/objects": {
        status: 422,
        body: { detail: { code: "propriete_non_filtrable", detail: "contact_email" } },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));

    const refus = await screen.findByRole("alert");
    expect(refus).toHaveTextContent("“contact_email” cannot be filtered on");
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
    // Aucune recherche offerte sur un espace refusé : sa table peut ne pas exister.
    expect(screen.queryByRole("form", { name: "Search filters" })).not.toBeInTheDocument();
  });

  it("distingue une table pas encore posée d'une table vide", async () => {
    monte({
      "GET /api/storages": {
        status: 200,
        body: [{ ...ACCOUNTS, applied_at: null, version_number: null }],
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));

    expect(
      await screen.findByText(/table is not created yet/),
    ).toBeInTheDocument();
    expect(screen.queryByText("No object matches.")).not.toBeInTheDocument();
  });

  it("revient à la première page quand un critère change", async () => {
    // Rester en page 4 d'une recherche qui n'a plus que deux pages afficherait un vide
    // qu'on prendrait pour un résultat.
    const calls = monte({
      ...UNE_LISTE,
      "GET /api/storages/accounts/objects": {
        status: 200,
        body: { objects: [OBJET], total: 120, page: 1, page_size: 50 },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));
    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();

    const form = () => within(screen.getByRole("form", { name: "Search filters" }));
    fireEvent.click(form().getByRole("button", { name: "Add a filter" }));
    fireEvent.change(form().getByLabelText("Property"), { target: { value: "contact_phone" } });
    fireEvent.change(form().getByLabelText("Value"), { target: { value: "01" } });

    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toContain(
      "GET /api/storages/accounts/objects?f=contact_phone%3Aeq%3A01&page=1",
    );
  });
});
