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
  cle: '["A-1"]',
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
    // Sur la ligne de l'index qui la porte : le chemin paraît aussi en colonne de filtre
    // et en tête de table, et `getByText` y trouverait trois éléments.
    expect(screen.getByText("tel").closest("li")).toHaveTextContent("$.Contact.Phone");
  });

  it("porte une colonne de filtre par propriété filtrable, et rien d'autre", async () => {
    // La même règle que l'arbre des propriétés du portail : on ne propose que ce qui
    // marche, plutôt que de laisser découvrir le refus après coup. Une colonne par
    // propriété (Gael, 04/11/2026) : il n'y a plus de filtre à ajouter ni de propriété
    // à choisir, donc plus de critère incomplet silencieusement ignoré.
    monte(UNE_PAGE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));
    const filtres = within(screen.getByRole("form", { name: "Search filters" }));

    const colonnes = filtres.getAllByRole("textbox").map((champ) => champ.id);
    expect(colonnes).toEqual(["filtre-cle", "filtre-contact_phone", "filtre-postes"]);
    expect(filtres.getByLabelText("$.AccountId")).toBeInTheDocument();
    expect(filtres.getByLabelText("$.Contact.Phone")).toBeInTheDocument();
  });

  it("cherche en « contient » par défaut sur une colonne de texte", async () => {
    const calls = monte(UNE_PAGE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));
    const form = () => within(screen.getByRole("form", { name: "Search filters" }));
    fireEvent.change(form().getByLabelText("$.Contact.Phone"), { target: { value: "0102" } });

    expect(await screen.findByText("A-1")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toContain(
      "GET /api/storages/accounts/objects?f=contact_phone%3Acontient%3A0102&page=1",
    );
  });

  it("n'offre aucune comparaison textuelle sur une colonne qui n'est pas du texte", async () => {
    // Le serveur les refuse : les proposer ferait découvrir le refus après coup.
    monte(UNE_PAGE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));
    const filtres = within(screen.getByRole("form", { name: "Search filters" }));

    const proposees = within(filtres.getByLabelText("Comparison on $.Postes"))
      .getAllByRole<HTMLOptionElement>("option")
      .map((option) => option.value);
    expect(proposees).toEqual(["eq", "ne", "gt", "ge", "lt", "le"]);
  });

  it("cherche la clé fonctionnelle telle qu'on la lit, pas telle qu'elle est rangée", async () => {
    // La base range `["A-1"]` ; la personne tape « A-1 ». « contient » traverse la forme
    // canonique, et c'est ce qui fait que le filtre par défaut trouve.
    const calls = monte(UNE_PAGE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));
    const form = () => within(screen.getByRole("form", { name: "Search filters" }));
    fireEvent.change(form().getByLabelText("$.AccountId"), { target: { value: "A-1" } });

    expect(await screen.findByText("A-1")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toContain(
      "GET /api/storages/accounts/objects?f=cle%3Acontient%3AA-1&page=1",
    );
  });

  it("compose la forme canonique de la clé pour une égalité", async () => {
    // « égale » compare la chaîne ENTIÈRE : sans le tableau JSON, elle ne trouverait
    // jamais rien, et l'écran aurait l'air de ne pas filtrer.
    const calls = monte(UNE_PAGE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));
    const form = () => within(screen.getByRole("form", { name: "Search filters" }));
    fireEvent.change(form().getByLabelText("Comparison on $.AccountId"), {
      target: { value: "eq" },
    });
    fireEvent.change(form().getByLabelText("$.AccountId"), { target: { value: "A-1" } });

    expect(await screen.findByText("A-1")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toContain(
      `GET /api/storages/accounts/objects?f=${encodeURIComponent('cle:eq:["A-1"]')}&page=1`,
    );
  });

  it("n'interroge pas le serveur tant qu'aucune valeur n'est saisie", async () => {
    // Les colonnes de filtre sont toutes là dès l'ouverture, et toutes vides : les
    // envoyer ferait refuser la recherche pour un geste que personne n'a fait.
    const calls = monte(UNE_PAGE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));
    expect(await screen.findByText("A-1")).toBeInTheDocument();

    expect(calls.map((c) => c.key)).toContain(
      "GET /api/storages/accounts/objects?page=1",
    );
  });

  it("rend l'objet, ses colonnes projetées et ses deux dates", async () => {
    monte(UNE_PAGE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));

    expect(await screen.findByText("1 object found")).toBeInTheDocument();
    // La clé telle qu'on la LIT : la base range `["A-1"]`, et ce crochet n'apprend rien.
    expect(screen.getByRole("button", { name: "A-1" })).toBeInTheDocument();
    // La valeur de la colonne projetée est affichée : c'est elle qui dit pourquoi cet
    // objet est dans le résultat.
    expect(screen.getByText("0102030405")).toBeInTheDocument();
    // Les colonnes sont nommées par leur chemin déclaré, au-dessus de la table.
    const table = within(screen.getByRole("region", { name: "Objects found" }));
    expect(table.getByText("$.Contact.Phone")).toBeInTheDocument();
  });

  it("montre le modèle de l'objet à droite quand on clique la ligne", async () => {
    // Rendu sous chaque ligne, le modèle donnait vingt lignes de JSON par objet et la
    // table cessait d'être parcourable (Gael, 04/11/2026).
    monte(UNE_PAGE);

    fireEvent.click(await screen.findByRole("button", { name: "Accounts" }));
    expect(await screen.findByText("1 object found")).toBeInTheDocument();
    // Avant le clic, le panneau invite à choisir : aucun modèle n'est montré.
    expect(screen.getByText("Pick a row to see its model.")).toBeInTheDocument();
    expect(screen.queryByText(/"AccountId"/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "A-1" }));

    const detail = within(screen.getByRole("complementary", { name: "Object" }));
    expect(detail.getByText(/"AccountId": "A-1"/)).toBeInTheDocument();
    expect(detail.getByText(/seen on/)).toBeInTheDocument();
    expect(detail.getByText(/changed on/)).toBeInTheDocument();
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
    fireEvent.change(form().getByLabelText("$.Contact.Phone"), { target: { value: "01" } });

    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toContain(
      "GET /api/storages/accounts/objects?f=contact_phone%3Acontient%3A01&page=1",
    );
  });
});
