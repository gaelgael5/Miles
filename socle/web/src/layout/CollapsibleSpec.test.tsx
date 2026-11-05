import { fireEvent, render, screen } from "@testing-library/react";

import "../i18n/i18n";
import { CollapsibleSpec } from "./CollapsibleSpec";

function Vue() {
  return (
    <CollapsibleSpec>
      <div data-testid="document">le document</div>
    </CollapsibleSpec>
  );
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("le repli de la description d'un contrat", () => {
  it("replie la description sans retirer le document", () => {
    // Ce qui se replie est la prose d'en-tête, pas le contrat : les adresses et les
    // schémas restent là. La classe le dit, et c'est elle que la feuille lit — on ne
    // touche pas au DOM de Swagger, qu'il reconstruit à chaque document.
    const { container } = render(<Vue />);
    const bouton = screen.getByRole("button", { name: "Hide the description" });
    expect(bouton).toHaveAttribute("aria-expanded", "true");
    expect(container.querySelector(".spec-host")).not.toHaveClass("spec-folded");

    fireEvent.click(bouton);

    expect(screen.getByRole("button", { name: "Show the description" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(container.querySelector(".spec-host")).toHaveClass("spec-folded");
    expect(screen.getByTestId("document")).toBeInTheDocument();
  });

  it("commande la zone qu'il replie, et la retrouve repliée au retour", () => {
    // `aria-controls` désigne la zone : sans lui, le bouton annonce un repli dont rien
    // ne dit ce qu'il replie. Et le choix est mémorisé — qui l'a replié une fois l'a lu,
    // et le rouvrir à chaque source défait le geste à chaque fois.
    const { container, unmount } = render(<Vue />);
    const zone = container.querySelector(".spec-host");
    expect(screen.getByRole("button")).toHaveAttribute("aria-controls", zone?.id ?? "");

    fireEvent.click(screen.getByRole("button"));
    unmount();
    const revenu = render(<Vue />);

    expect(screen.getByRole("button", { name: "Show the description" })).toBeInTheDocument();
    expect(revenu.container.querySelector(".spec-host")).toHaveClass("spec-folded");
  });
});
