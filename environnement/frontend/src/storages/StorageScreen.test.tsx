import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { type Routes, mockApi } from "@miles/socle-web/testing";

import "../i18n/i18n";
import type { Storage } from "../api/storages";
import { StorageScreen } from "./StorageScreen";

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
// La clé sous la forme que la base porte RÉELLEMENT : un tableau JSON, même pour une clé
// d'une seule partie. Le jeu d'essai portait « A-1 », une forme que l'ingestion n'écrit
// nulle part — et c'est ce qui laissait passer une recherche par clé fausse.
const OBJET = {
  cle: '["A-1"]',
  objet: { AccountId: "A-1", Postes: 3 },
  vu_le: "2026-11-02T07:10:00Z",
  modifie_le: "2026-11-02T07:10:00Z",
  origine: "import",
  // Les imports le portent : pas de marque d'absence. Renseigné et non omis — un champ
  // absent de la doublure n'est pas `null` mais `undefined`, et l'écran afficherait la
  // marque sur un objet qui n'en a pas.
  absent_depuis: null,
  columns: { contact_phone: "0102030405", postes: 3 },
};
// Le même objet, ABSENT de l'import depuis une date. L'écran doit continuer de le rendre.
const OBJET_ABSENT = { ...OBJET, cle: '["A-2"]', absent_depuis: "2026-11-09T06:00:00Z" };

function monte(routes: Routes, name = "accounts") {
  const calls = mockApi(routes);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <StorageScreen name={name} />
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
const filtres = () => within(screen.getByRole("form", { name: "Search filters" }));

describe("la page d'un espace de stockage", () => {
  it("montre la clé fonctionnelle et les index sous leur chemin DÉCLARÉ", async () => {
    // Pas « contact_phone » : c'est sous « $.Contact.Phone » que la personne a choisi la
    // propriété dans le portail, et le nom de colonne dérivé ne lui dirait pas lequel de
    // ses index elle regarde.
    monte(UNE_PAGE);

    expect(await screen.findByText(/Functional key: \$\.AccountId/)).toBeInTheDocument();
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
    expect(await screen.findByText("1 object found")).toBeInTheDocument();

    const colonnes = filtres()
      .getAllByRole("textbox")
      .map((champ) => champ.id);
    expect(colonnes).toEqual(["filtre-cle", "filtre-contact_phone", "filtre-postes"]);
    expect(filtres().getByLabelText("$.AccountId")).toBeInTheDocument();
    expect(filtres().getByLabelText("$.Contact.Phone")).toBeInTheDocument();
  });

  it("cherche en « contient » par défaut sur une colonne de texte", async () => {
    const calls = monte(UNE_PAGE);
    expect(await screen.findByText("1 object found")).toBeInTheDocument();

    fireEvent.change(filtres().getByLabelText("$.Contact.Phone"), { target: { value: "0102" } });

    await waitFor(() =>
      expect(calls.map((c) => c.key)).toContain(
        "GET /api/storages/accounts/objects?f=contact_phone%3Acontient%3A0102&page=1",
      ),
    );
  });

  it("n'offre aucune comparaison textuelle sur une colonne qui n'est pas du texte", async () => {
    // Le serveur les refuse : les proposer ferait découvrir le refus après coup.
    monte(UNE_PAGE);
    expect(await screen.findByText("1 object found")).toBeInTheDocument();

    const proposees = within(filtres().getByLabelText("Comparison on $.Postes"))
      .getAllByRole<HTMLOptionElement>("option")
      .map((option) => option.value);
    expect(proposees).toEqual(["eq", "ne", "gt", "ge", "lt", "le"]);
  });

  it("cherche la clé fonctionnelle telle qu'on la lit, pas telle qu'elle est rangée", async () => {
    // La base range `["A-1"]` ; la personne tape « A-1 ». « contient » traverse la forme
    // canonique, et c'est ce qui fait que le filtre par défaut trouve.
    const calls = monte(UNE_PAGE);
    expect(await screen.findByText("1 object found")).toBeInTheDocument();

    fireEvent.change(filtres().getByLabelText("$.AccountId"), { target: { value: "A-1" } });

    await waitFor(() =>
      expect(calls.map((c) => c.key)).toContain(
        "GET /api/storages/accounts/objects?f=cle%3Acontient%3AA-1&page=1",
      ),
    );
  });

  it("compose la forme canonique de la clé pour une égalité", async () => {
    // « égale » compare la chaîne ENTIÈRE : sans le tableau JSON, elle ne trouverait
    // jamais rien, et l'écran aurait l'air de ne pas filtrer.
    const calls = monte(UNE_PAGE);
    expect(await screen.findByText("1 object found")).toBeInTheDocument();

    fireEvent.change(filtres().getByLabelText("Comparison on $.AccountId"), {
      target: { value: "eq" },
    });
    fireEvent.change(filtres().getByLabelText("$.AccountId"), { target: { value: "A-1" } });

    await waitFor(() =>
      expect(calls.map((c) => c.key)).toContain(
        `GET /api/storages/accounts/objects?f=${encodeURIComponent('cle:eq:["A-1"]')}&page=1`,
      ),
    );
  });

  it("n'interroge pas le serveur tant qu'aucune valeur n'est saisie", async () => {
    // Les colonnes de filtre sont toutes là dès l'ouverture, et toutes vides : les
    // envoyer ferait refuser la recherche pour un geste que personne n'a fait.
    const calls = monte(UNE_PAGE);

    expect(await screen.findByText("1 object found")).toBeInTheDocument();
    expect(calls.map((c) => c.key)).toContain("GET /api/storages/accounts/objects?page=1");
  });

  it("rend l'objet et ses colonnes projetées, sans répéter la date du panneau", async () => {
    // La date de dernière vue est dans le panneau, et elle n'est plus une colonne
    // (Gael, 05/11/2026) : elle prenait une colonne entière pour une valeur identique
    // sur tout un import, au détriment des colonnes qui distinguent les objets.
    monte(UNE_PAGE);

    expect(await screen.findByText("1 object found")).toBeInTheDocument();
    // La clé telle qu'on la LIT : la base range `["A-1"]`, et ce crochet n'apprend rien.
    expect(screen.getByRole("button", { name: "A-1" })).toBeInTheDocument();
    // La valeur de la colonne projetée est affichée : c'est elle qui dit pourquoi cet
    // objet est dans le résultat.
    expect(screen.getByText("0102030405")).toBeInTheDocument();
    // Les colonnes sont nommées par leur chemin déclaré, au-dessus de la table.
    const table = within(screen.getByRole("region", { name: "Objects found" }));
    expect(table.getByText("$.Contact.Phone")).toBeInTheDocument();
    expect(table.queryByText(/2026/)).not.toBeInTheDocument();
  });

  it("montre dans la LISTE quels objets sont absents de l'import, et les rend quand même", async () => {
    // « On doit pouvoir voir ce qui est absent avant qu'une règle ne le supprime »
    // (story `82bc9dca`) : sans marque dans la liste, il faudrait ouvrir les objets un
    // par un. Et un objet marqué reste rendu — la lecture ne le filtre jamais.
    monte({
      ...UNE_LISTE,
      "GET /api/storages/accounts/objects": {
        status: 200,
        body: { objects: [OBJET, OBJET_ABSENT], total: 2, page: 1, page_size: 50 },
      },
    });

    expect(await screen.findByText("2 objects found")).toBeInTheDocument();
    const table = within(screen.getByRole("region", { name: "Objects found" }));
    // Une seule marque pour deux objets : celui que l'import porte n'en a pas.
    expect(table.getAllByText("missing from the import")).toHaveLength(1);
    expect(table.getByRole("button", { name: "A-1" })).toBeInTheDocument();
    expect(table.getByRole("button", { name: "A-2" })).toBeInTheDocument();
  });

  it("dit depuis quand un objet est absent de l'import, dans son panneau", async () => {
    monte({
      ...UNE_LISTE,
      "GET /api/storages/accounts/objects": {
        status: 200,
        body: { objects: [OBJET_ABSENT], total: 1, page: 1, page_size: 50 },
      },
    });
    expect(await screen.findByText("1 object found")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "A-2" }));

    const detail = within(screen.getByRole("complementary", { name: "Object" }));
    expect(detail.getByText(/missing from the import since/)).toBeInTheDocument();
  });

  it("ne dit rien de l'absence sur un objet que l'import porte", async () => {
    // Rien du tout, et non un « — » : une absence vide se lirait comme une donnée
    // manquante. C'est aussi ce test qui mordrait si la doublure omettait le champ.
    monte(UNE_PAGE);
    expect(await screen.findByText("1 object found")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "A-1" }));

    expect(screen.queryByText(/missing from the import/)).not.toBeInTheDocument();
  });

  it("ne garde pas la colonne de clé quand une colonne du modèle la porte déjà", async () => {
    // Gael, 05/11/2026 : depuis que le modèle coche ce que la table montre, « $.Id » est
    // la première colonne, et la colonne de clé la répétait mot pour mot. C'est alors la
    // première colonne qui ouvre l'objet — le geste ne part pas avec la colonne.
    const PORTE_LA_CLE: Storage = {
      ...ACCOUNTS,
      projections: [
        { column: "prop_id", path: "$.AccountId", kind: "string", sql_type: "text" },
        ...ACCOUNTS.projections,
      ],
    };
    monte({
      "GET /api/storages": { status: 200, body: [PORTE_LA_CLE] },
      "GET /api/storages/accounts/objects": {
        status: 200,
        body: {
          objects: [{ ...OBJET, columns: { ...OBJET.columns, prop_id: "A-1" } }],
          total: 1,
          page: 1,
          page_size: 50,
        },
      },
    });
    expect(await screen.findByText("1 object found")).toBeInTheDocument();

    const table = within(screen.getByRole("region", { name: "Objects found" }));
    expect(table.queryByText("Key")).not.toBeInTheDocument();
    fireEvent.click(table.getByRole("button", { name: "A-1" }));

    const detail = within(screen.getByRole("complementary", { name: "Object" }));
    expect(detail.getByText(/"AccountId": "A-1"/)).toBeInTheDocument();
  });

  it("montre le modèle de l'objet à droite quand on clique la ligne", async () => {
    // Rendu sous chaque ligne, le modèle donnait vingt lignes de JSON par objet et la
    // table cessait d'être parcourable (Gael, 04/11/2026).
    monte(UNE_PAGE);
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

    expect(await screen.findByText("No object matches.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    // Et on ne le dit qu'UNE fois : « 0 object found » au-dessus de « No object
    // matches » disait deux fois la même chose, dont une en capitales.
    expect(screen.queryByText(/objects? found/)).not.toBeInTheDocument();
  });

  it("nomme la propriété quand le serveur refuse le critère", async () => {
    monte({
      ...UNE_LISTE,
      "GET /api/storages/accounts/objects": {
        status: 422,
        body: { detail: { code: "propriete_non_filtrable", detail: "contact_email" } },
      },
    });

    const refus = await screen.findByRole("alert");
    expect(refus).toHaveTextContent("“contact_email” cannot be filtered on");
  });

  it("dit que la table est en retard sur la version servie, et le geste qui la rattrape", async () => {
    // Arrivé le 05/11/2026 : le modèle s'est mis à déclarer des colonnes, la déclaration
    // suit la version servie et la table ne change qu'à la POSE d'une version. Entre les
    // deux, la lecture tombait sur une erreur SQL brute et un 500.
    monte({
      ...UNE_LISTE,
      "GET /api/storages/accounts/objects": {
        status: 409,
        body: { detail: { code: "table_en_retard", detail: "prop_id, name" } },
      },
    });

    const refus = await screen.findByRole("alert");
    expect(refus).toHaveTextContent("prop_id, name is missing");
    expect(refus).toHaveTextContent("Send the version order again");
  });

  it("n'offre aucune recherche sur un espace refusé, et dit pourquoi", async () => {
    // Sa table peut ne pas exister : le formulaire promettrait un geste impossible.
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
    expect(screen.queryByRole("form", { name: "Search filters" })).not.toBeInTheDocument();
  });

  it("distingue une table pas encore posée d'une table vide", async () => {
    monte({
      "GET /api/storages": {
        status: 200,
        body: [{ ...ACCOUNTS, applied_at: null, version_number: null }],
      },
    });

    expect(await screen.findByText(/table is not created yet/)).toBeInTheDocument();
    expect(screen.queryByText("No object matches.")).not.toBeInTheDocument();
  });

  it("dit qu'un espace a disparu de la version servie, plutôt qu'un écran vide", async () => {
    // La page reste ouverte quand une version suivante ne déclare plus l'espace : sans
    // ce message, elle se viderait sans qu'on sache si c'est une panne.
    monte(UNE_LISTE, "sites");

    expect(
      await screen.findByText(/no longer declares a “sites” space/),
    ).toBeInTheDocument();
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
    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();

    fireEvent.change(filtres().getByLabelText("$.Contact.Phone"), { target: { value: "01" } });

    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.map((c) => c.key)).toContain(
        "GET /api/storages/accounts/objects?f=contact_phone%3Acontient%3A01&page=1",
      ),
    );
  });
});
