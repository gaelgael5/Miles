import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PairingScreen } from "@miles/socle-web";
import { mockApi, type Routes } from "@miles/socle-web/testing";
import { render, screen } from "@testing-library/react";

import "../i18n/i18n";

// L'écran d'appariement est celui du socle, employé TEL QUEL : le module de paramétrage
// n'ajoute aucun geste, et ce qu'il recevra — les connexions git — viendra avec son
// ticket. Il n'y a donc rien à éprouver de l'écran lui-même, éprouvé au socle.
//
// Ce qui est éprouvé ICI est ce que le socle ne peut pas dire : ses libellés neutres,
// redéfinis par ce produit. Sans ce test, la redéfinition pourrait sauter sans que rien ne
// rougisse — l'écran afficherait « ce module », qui n'est pas faux, seulement moins vrai —
// et un administrateur lirait sur l'écran du portail un texte écrit pour un environnement.

function monte(routes: Routes) {
  mockApi(routes);
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <PairingScreen />
    </QueryClientProvider>,
  );
}

describe("écran d'appariement du module de paramétrage", () => {
  it("names what this module is, and why it pairs with only one enrolment module", async () => {
    monte({
      "GET /api/identity/pairing/state": {
        status: 200,
        body: { state: "non_apparie", attempt: null, peer: null },
      },
    });

    expect(await screen.findByText(/configuration module pairs with a single/i)).toBeInTheDocument();
    expect(
      screen.getByText(/two authorities over the same secrets/i),
    ).toBeInTheDocument();
    // Et le champ du formulaire nomme CE module, pas « cet environnement ».
    expect(screen.getByLabelText("Name of this configuration module")).toBeInTheDocument();
  });
});
