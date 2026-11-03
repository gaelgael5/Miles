import { act, render, screen } from "@testing-library/react";
import { useTranslation } from "react-i18next";

import i18n from "./i18n";
import { useInstant } from "./instants";

// Le 2 novembre 2026 : la SEULE date qui éprouve quelque chose ici. Un jour supérieur à
// douze (« 20/11 ») se lit pareil dans les deux cultures à l'ordre près, et une date
// comme le 11 novembre est un palindrome — les deux resteraient vertes sur le défaut.
const DEUX_NOVEMBRE = "2026-11-02T10:21:29+00:00";

function Ligne() {
  const instant = useInstant();
  // `t` monte l'abonnement i18next du composant, exactement comme un écran réel : c'est
  // lui qui provoque le rendu au changement de langue, et donc la relecture de la culture.
  useTranslation();
  return <p>{instant(DEUX_NOVEMBRE)}</p>;
}

describe("useInstant", () => {
  afterEach(async () => {
    // Les tests du dépôt tournent en en-US : on rend la culture telle qu'on l'a trouvée.
    await i18n.changeLanguage("en-US");
  });

  it("formats an instant in the US order when the interface is in en-US", () => {
    render(<Ligne />);

    expect(screen.getByText(/^11\/2\/2026/)).toBeInTheDocument();
  });

  it("formats an instant in the FRENCH order when the interface is in fr-FR", async () => {
    await i18n.changeLanguage("fr-FR");

    render(<Ligne />);

    // 02/11, et non 11/02 : c'est le 2 novembre. C'est l'assertion que le défaut
    // d'origine faisait échouer, et qu'aucun test en en-US ne pouvait porter.
    expect(screen.getByText(/^02\/11\/2026/)).toBeInTheDocument();
  });

  it("re-reads the culture when the interface language changes under it", async () => {
    render(<Ligne />);
    expect(screen.getByText(/^11\/2\/2026/)).toBeInTheDocument();

    // Dans `act` : le changement de langue provoque un rendu, et React demande que les
    // rendus déclenchés par un test y soient enveloppés.
    await act(() => i18n.changeLanguage("fr-FR"));

    // La raison d'être du hook : une fonction qui lirait la culture au chargement du
    // module laisserait la date dans l'ancienne culture jusqu'à un rendu venu d'ailleurs.
    expect(await screen.findByText(/^02\/11\/2026/)).toBeInTheDocument();
  });
});
