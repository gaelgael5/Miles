// FUSEAU FORCÉ À L'OUEST DE GREENWICH, et c'est toute la raison d'être de ce fichier
// séparé : posé avant tout usage de `Date` ou d'`Intl`, il met le processus dans la
// situation où le défaut existe. Les tests du dépôt tournent en UTC par convention —
// c'est-à-dire exactement dans le seul fuseau où un décalage d'un jour est invisible, et
// la convention elle-même devient donc suspecte dès qu'on veut l'éprouver (leçon du
// 02/11/2026, même famille que la culture du navigateur).
process.env.TZ = "America/New_York";

import { act, render, screen } from "@testing-library/react";
import { useTranslation } from "react-i18next";

import i18n from "./i18n";
import { useCalendarDate } from "./instants";

// Le 14 juillet 2026, qui discrimine deux fois à la fois : le jour est ≤ 12 ? non — mais
// ici ce n'est pas l'ordre jour/mois qui compte d'abord, c'est le JOUR lui-même. Minuit
// UTC le 14 vaut 20 h le 13 à New York : sans la garde, l'écran écrit « 13 juillet ».
const QUATORZE_JUILLET = "2026-07-14";
// Le 2 novembre, pour l'ordre des composantes : « 11/2 » contre « 2/11 ». Un jour > 12 se
// lirait pareil dans les deux cultures à l'ordre près.
const DEUX_NOVEMBRE = "2026-11-02";

function Jour({ value }: { value: string }) {
  const jour = useCalendarDate();
  // `t` monte l'abonnement i18next, exactement comme un écran réel : c'est lui qui
  // provoque le rendu au changement de langue.
  useTranslation();
  return <p>{jour(value)}</p>;
}

describe("useCalendarDate", () => {
  afterEach(async () => {
    await i18n.changeLanguage("en-US");
  });

  it("ne recule PAS d'un jour dans un fuseau à l'ouest de Greenwich", () => {
    render(<Jour value={QUATORZE_JUILLET} />);

    // L'assertion qui mord : sans `timeZone: "UTC"`, ce texte porterait « July 13 ».
    // Une date civile n'a pas de fuseau — c'est une case de calendrier, pas un instant.
    expect(screen.getByText(/July 14, 2026/)).toBeInTheDocument();
    expect(screen.queryByText(/July 13/)).not.toBeInTheDocument();
  });

  it("formate dans la culture de l'INTERFACE et non celle du navigateur", async () => {
    await act(() => i18n.changeLanguage("fr-FR"));

    render(<Jour value={DEUX_NOVEMBRE} />);

    expect(screen.getByText(/2 novembre 2026/)).toBeInTheDocument();
  });

  it("dit le jour de la semaine, qu'on vient précisément lire sur un calendrier", () => {
    render(<Jour value={QUATORZE_JUILLET} />);

    // Le 14 juillet 2026 est un mardi. Savoir qu'une fête tombe un samedi est l'usage
    // même de cet écran.
    expect(screen.getByText(/^Tuesday/)).toBeInTheDocument();
  });

  it("n'affiche AUCUNE heure : le minuit du transport n'est pas une donnée", () => {
    render(<Jour value={DEUX_NOVEMBRE} />);

    expect(screen.queryByText(/00:00|12:00|AM|PM/)).not.toBeInTheDocument();
  });
});
