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
  it("arrive REPLIÉ, et déplie sans jamais retirer le document", () => {
    // Replié par défaut (Gael, 05/11/2026) : la même prose coiffe le contrat de chaque
    // source et repousse les adresses hors du premier écran. Ce qui se replie est elle,
    // pas le contrat — la classe le dit, et c'est elle que la feuille lit : on ne touche
    // pas au DOM de Swagger, qu'il reconstruit à chaque document.
    const { container } = render(<Vue />);
    const chevron = screen.getByRole("button", { name: "Show the description" });
    expect(chevron).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelector(".spec-host")).toHaveClass("spec-folded");
    expect(screen.getByTestId("document")).toBeInTheDocument();

    fireEvent.click(chevron);

    expect(screen.getByRole("button", { name: "Hide the description" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(container.querySelector(".spec-host")).not.toHaveClass("spec-folded");
  });

  it("commande la zone qu'il replie, et la retrouve dépliée au retour", () => {
    // `aria-controls` désigne la zone : une flèche seule, sans lui, annonce un repli
    // dont rien ne dit ce qu'il replie. Et le choix de DÉPLIER se mémorise lui aussi,
    // sans quoi il faudrait le refaire à chaque source.
    const { container, unmount } = render(<Vue />);
    const zone = container.querySelector(".spec-host");
    expect(screen.getByRole("button")).toHaveAttribute("aria-controls", zone?.id ?? "");

    fireEvent.click(screen.getByRole("button"));
    unmount();
    const revenu = render(<Vue />);

    expect(screen.getByRole("button", { name: "Hide the description" })).toBeInTheDocument();
    expect(revenu.container.querySelector(".spec-host")).not.toHaveClass("spec-folded");
  });
});
