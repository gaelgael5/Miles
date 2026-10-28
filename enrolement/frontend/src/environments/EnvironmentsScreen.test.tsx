import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { EnvironmentsScreen } from "./EnvironmentsScreen";
import "../i18n/i18n";

const RECETTE = {
  id: "11111111-1111-4111-8111-111111111111",
  slug: "recette-nord",
  label: "Recette nord",
  created_at: "2026-10-28T09:00:00+00:00",
  updated_at: "2026-10-28T09:00:00+00:00",
  paired_base_url: null,
};

const PRODUCTION = {
  ...RECETTE,
  id: "22222222-2222-4222-8222-222222222222",
  slug: "production",
  label: "Production",
  paired_base_url: "https://prod.exemple.org",
};

function liste(body: unknown): Routes {
  return { "GET /api/environments": { status: 200, body } };
}

function monte(routes: Routes) {
  const calls = mockApi(routes);
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <EnvironmentsScreen />
    </QueryClientProvider>,
  );
  return calls;
}

function champs() {
  return {
    label: screen.getByLabelText("Label") as HTMLInputElement,
    slug: screen.getByLabelText("Slug") as HTMLInputElement,
  };
}

describe("référentiel des environnements", () => {
  it("shows the label, the slug and which stack is paired", async () => {
    monte(liste([RECETTE, PRODUCTION]));

    expect(await screen.findByText("Recette nord")).toBeInTheDocument();
    expect(screen.getByText("recette-nord")).toBeInTheDocument();
    expect(screen.getByText("Not paired")).toBeInTheDocument();
    expect(screen.getByText("Paired")).toBeInTheDocument();
    expect(screen.getByText("https://prod.exemple.org")).toBeInTheDocument();
  });

  it("says the list is empty rather than showing nothing at all", async () => {
    monte(liste([]));

    expect(await screen.findByText("No environment declared yet.")).toBeInTheDocument();
  });

  it("fills the slug from the label", async () => {
    monte(liste([]));
    await screen.findByText("No environment declared yet.");

    fireEvent.change(champs().label, { target: { value: "Recette Nord — été 2026" } });

    // Accents translittérés, casse abaissée, ponctuation devenue séparateur, et aucun
    // trait d'union au bord.
    expect(champs().slug.value).toBe("recette-nord-ete-2026");
  });

  it("stops rewriting the slug once it has been chosen by hand", async () => {
    // La panne classique de ce couple de champs : corriger le libellé après avoir choisi
    // son slug effacerait le choix sans rien dire.
    monte(liste([]));
    await screen.findByText("No environment declared yet.");

    fireEvent.change(champs().label, { target: { value: "Recette" } });
    fireEvent.change(champs().slug, { target: { value: "rec-n" } });
    fireEvent.change(champs().label, { target: { value: "Recette nord" } });

    expect(champs().slug.value).toBe("rec-n");
  });

  it("invents no slug when the label gives nothing usable", async () => {
    // Un slug que personne n'a choisi est un slug que personne ne reconnaît : le champ
    // reste vide et c'est l'humain qui le remplit.
    monte(liste([]));
    await screen.findByText("No environment declared yet.");

    fireEvent.change(champs().label, { target: { value: "— … !" } });

    expect(champs().slug.value).toBe("");
  });

  it("sends the label and the slug that were typed", async () => {
    const appels = monte({
      ...liste([]),
      "POST /api/environments": { status: 201, body: RECETTE },
    });
    await screen.findByText("No environment declared yet.");

    fireEvent.change(champs().label, { target: { value: "Recette nord" } });
    fireEvent.click(screen.getByRole("button", { name: "Declare" }));

    await waitFor(() =>
      expect(appels.find((appel) => appel.key === "POST /api/environments")?.body).toEqual({
        label: "Recette nord",
        slug: "recette-nord",
      }),
    );
  });

  it("names the slug collision rather than the field", async () => {
    // La saisie est bien formée : c'est l'état du référentiel qui la refuse, et retaper
    // un slug correct ne règle pas une collision.
    monte({
      ...liste([]),
      "POST /api/environments": { status: 409, body: { detail: "slug_pris" } },
    });
    await screen.findByText("No environment declared yet.");

    fireEvent.change(champs().label, { target: { value: "Recette nord" } });
    fireEvent.click(screen.getByRole("button", { name: "Declare" }));

    expect(await screen.findByText(/already carries this slug/i)).toBeInTheDocument();
  });

  it("names the offending field on a refused entry", async () => {
    monte({
      ...liste([]),
      "POST /api/environments": { status: 422, body: { detail: "slug" } },
    });
    await screen.findByText("No environment declared yet.");

    fireEvent.click(screen.getByRole("button", { name: "Declare" }));

    expect(await screen.findByText(/lowercase letters, digits and hyphens/i)).toBeInTheDocument();
  });

  it("opens the rename form on the chosen environment, slug untouched by the label", async () => {
    monte(liste([RECETTE]));

    fireEvent.click(await screen.findByRole("button", { name: "Rename" }));

    expect(champs().label.value).toBe("Recette nord");
    expect(champs().slug.value).toBe("recette-nord");

    fireEvent.change(champs().label, { target: { value: "Recette sud" } });

    // Le slug a été choisi une fois : renommer le libellé ne le reprend pas à son auteur.
    expect(champs().slug.value).toBe("recette-nord");
  });

  it("asks before deleting, and names what disappears", async () => {
    const appels = monte({
      ...liste([RECETTE]),
      "DELETE /api/environments/11111111-1111-4111-8111-111111111111": { status: 204, body: null },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialogue = within(screen.getByRole("dialog"));
    expect(dialogue.getByText(/Recette nord will disappear/i)).toBeInTheDocument();
    // Tant qu'on n'a pas confirmé, rien n'est envoyé.
    expect(appels.some((appel) => appel.key.startsWith("DELETE"))).toBe(false);

    fireEvent.click(dialogue.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(appels.some((appel) => appel.key.startsWith("DELETE"))).toBe(true),
    );
  });

  it("tells to revoke first when the environment carries a pairing", async () => {
    monte({
      ...liste([PRODUCTION]),
      "DELETE /api/environments/22222222-2222-4222-8222-222222222222": {
        status: 409,
        body: { detail: "environnement_apparie" },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));

    expect(await screen.findByText(/Revoke it first/i)).toBeInTheDocument();
  });
});
