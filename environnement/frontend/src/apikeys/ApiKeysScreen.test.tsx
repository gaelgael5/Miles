import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { type Routes, mockApi } from "@miles/socle-web/testing";

import "../i18n/i18n";
import type { ApiKey } from "../api/apikeys";
import { ApiKeysScreen } from "./ApiKeysScreen";

// Manifestement fausse, comme côté portail : une valeur qui RESSEMBLE à une clé
// réelle dans un fichier versionné déclenche les scanners de secrets, et c'est le
// préfixe `mlk_` qui les y invite.
const SECRET = `mlk_${"k".repeat(43)}`;
const TRANSPORTEUR: ApiKey = {
  id: "a".repeat(32),
  label: "Transporteur",
  prefix: "mlk_kkkkkkkk",
  sources: ["comptes-pudo"],
  missing_sources: [],
  created_at: "2026-11-02T08:00:00Z",
  created_by: "admin@local",
  revoked_at: null,
  last_used_at: null,
};

function monte(routes: Routes) {
  const calls = mockApi(routes);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ApiKeysScreen />
    </QueryClientProvider>,
  );
  return calls;
}

const SOURCES: Routes = {
  "GET /api/api-keys/sources": {
    status: 200,
    body: { sources: ["comptes-pudo", "sites-pudo"] },
  },
};
const UNE_CLE: Routes = {
  ...SOURCES,
  "GET /api/api-keys": { status: 200, body: [TRANSPORTEUR] },
};

async function formulaire() {
  return within(await screen.findByRole("form", { name: "Issue a key" }));
}

describe("les clés d'API d'ingestion de l'environnement", () => {
  it("liste les clés avec leur préfixe et les sources qu'elles ouvrent", async () => {
    monte(UNE_CLE);

    // Portée à la LIGNE : « comptes-pudo » est aussi une case à cocher du formulaire,
    // et une assertion non portée resterait verte si la ligne ne disait pas ses octrois.
    const ligne = within(await screen.findByRole("listitem"));
    expect(ligne.getByText("Transporteur")).toBeInTheDocument();
    expect(ligne.getByText("mlk_kkkkkkkk…")).toBeInTheDocument();
    expect(ligne.getByText("comptes-pudo")).toBeInTheDocument();
    // Jamais utilisée se distingue d'utilisée : c'est ce qui permet de révoquer sans
    // risque, et une clé sans date ne doit pas s'afficher comme si elle servait.
    expect(ligne.getByText(/never used/)).toBeInTheDocument();
  });

  it("n'offre en octroi que les sources de la version servie", async () => {
    // La même règle que les filtres d'un storage : on ne propose que ce qui marche,
    // plutôt que de laisser découvrir le refus après la saisie.
    monte(UNE_CLE);

    const form = await formulaire();

    const cochables = form
      .getAllByRole<HTMLInputElement>("checkbox")
      .map((entree) => entree.closest("label")?.textContent);
    expect(cochables).toEqual(["comptes-pudo", "sites-pudo"]);
  });

  it("n'émet rien sans libellé ni sans octroi", async () => {
    // Le serveur refuserait les deux ; un refus qu'on peut empêcher de se produire vaut
    // mieux qu'un refus qu'on explique.
    const calls = monte(UNE_CLE);
    const form = await formulaire();

    expect(form.getByRole("button", { name: "Issue" })).toBeDisabled();

    fireEvent.change(form.getByLabelText("Label"), { target: { value: "Partenaire" } });
    expect(form.getByRole("button", { name: "Issue" })).toBeDisabled();

    fireEvent.click(form.getByRole("checkbox", { name: "comptes-pudo" }));
    expect(form.getByRole("button", { name: "Issue" })).toBeEnabled();
    expect(calls.map((c) => c.key)).not.toContain("POST /api/api-keys");
  });

  it("montre la clé émise une seule fois, et dit qu'elle ne se relira pas", async () => {
    monte({
      ...UNE_CLE,
      "POST /api/api-keys": {
        status: 201,
        body: { key: { ...TRANSPORTEUR, label: "Partenaire" }, secret: SECRET },
      },
    });
    const form = await formulaire();
    fireEvent.change(form.getByLabelText("Label"), { target: { value: "Partenaire" } });
    fireEvent.click(form.getByRole("checkbox", { name: "comptes-pudo" }));

    fireEvent.click(form.getByRole("button", { name: "Issue" }));

    expect(await screen.findByText(SECRET)).toBeInTheDocument();
    expect(screen.getByText(/shown once and cannot be read again/)).toBeInTheDocument();
    // Et elle disparaît de l'écran une fois le panneau fermé : aucun état ne la garde.
    fireEvent.click(screen.getByRole("button", { name: "I have copied the key" }));
    await waitFor(() => expect(screen.queryByText(SECRET)).not.toBeInTheDocument());
  });

  it("envoie le libellé et les octrois cochés, et rien d'autre", async () => {
    const calls = monte({
      ...UNE_CLE,
      "POST /api/api-keys": { status: 201, body: { key: TRANSPORTEUR, secret: SECRET } },
    });
    const form = await formulaire();
    fireEvent.change(form.getByLabelText("Label"), { target: { value: "Partenaire" } });
    fireEvent.click(form.getByRole("checkbox", { name: "sites-pudo" }));

    fireEvent.click(form.getByRole("button", { name: "Issue" }));

    await screen.findByText(SECRET);
    const envoi = calls.find((c) => c.key === "POST /api/api-keys");
    expect(envoi?.body).toEqual({ label: "Partenaire", sources: ["sites-pudo"] });
  });

  it("nomme la source quand le serveur refuse l'octroi", async () => {
    monte({
      ...UNE_CLE,
      "POST /api/api-keys": {
        status: 422,
        body: {
          detail: { field: "sources", reason: "source_inconnue", source: "inventee", declared: [] },
        },
      },
    });
    const form = await formulaire();
    fireEvent.change(form.getByLabelText("Label"), { target: { value: "Partenaire" } });
    fireEvent.click(form.getByRole("checkbox", { name: "comptes-pudo" }));

    fireEvent.click(form.getByRole("button", { name: "Issue" }));

    const refus = await screen.findByRole("alert");
    expect(refus).toHaveTextContent("does not declare source “inventee”");
  });

  it("signale un octroi dont la source a disparu de la version servie", async () => {
    // L'octroi reste écrit : une version suivante peut ramener la source, et le réécrire
    // d'office effacerait à qui on avait ouvert quoi.
    monte({
      ...SOURCES,
      "GET /api/api-keys": {
        status: 200,
        body: [
          {
            ...TRANSPORTEUR,
            sources: ["comptes-pudo", "retiree"],
            missing_sources: ["retiree"],
          },
        ],
      },
    });

    expect(await screen.findByText(/no longer declares: retiree/)).toBeInTheDocument();
  });

  it("révoque une clé, et une clé révoquée ne s'offre plus à la révocation", async () => {
    const calls = monte({
      ...UNE_CLE,
      "POST /api/api-keys/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/revoke": {
        status: 200,
        body: { ...TRANSPORTEUR, revoked_at: "2026-11-02T09:00:00Z" },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));

    await waitFor(() =>
      expect(calls.map((c) => c.key)).toContain(
        "POST /api/api-keys/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/revoke",
      ),
    );
  });

  it("montre une clé révoquée sans bouton, et sans l'effacer de la liste", async () => {
    monte({
      ...SOURCES,
      "GET /api/api-keys": {
        status: 200,
        body: [{ ...TRANSPORTEUR, revoked_at: "2026-11-02T09:00:00Z" }],
      },
    });

    expect(await screen.findByText(/Revoked on/)).toBeInTheDocument();
    expect(screen.getByText("Transporteur")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
  });

  it("dit qu'il n'y a rien à octroyer quand la version ne déclare aucune source", async () => {
    monte({
      "GET /api/api-keys": { status: 200, body: [] },
      "GET /api/api-keys/sources": { status: 200, body: { sources: [] } },
    });

    expect(await screen.findByText(/nothing to grant/)).toBeInTheDocument();
    // Et aucun formulaire inerte : il promettrait un geste impossible.
    expect(screen.queryByRole("form", { name: "Issue a key" })).not.toBeInTheDocument();
  });

  it("dit ce qu'il n'y a pas plutôt que de rendre une liste vide", async () => {
    monte({ ...SOURCES, "GET /api/api-keys": { status: 200, body: [] } });

    expect(await screen.findByText("No key has been issued yet.")).toBeInTheDocument();
  });

  it("dit que la lecture a échoué, sans faire croire qu'il n'y a aucune clé", async () => {
    monte({ ...SOURCES, "GET /api/api-keys": { status: 500, body: {} } });

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be read");
    expect(screen.queryByText("No key has been issued yet.")).not.toBeInTheDocument();
  });
});
