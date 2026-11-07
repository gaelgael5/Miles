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

describe("le repli de la description d'un contrat", () => {
  it("arrive REPLIÉ, et déplie sans jamais retirer le document", () => {
    // Replié par défaut : la même prose coiffe le contrat de chaque source et repousse
    // les adresses hors du premier écran. Ce qui se replie est elle, pas le contrat — la
    // classe le dit, et c'est elle que la feuille lit : on ne touche pas au DOM de
    // Swagger, qu'il reconstruit à chaque document.
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

  it("commande la zone qu'il replie", () => {
    // `aria-controls` désigne la zone : une flèche seule, sans lui, annonce un repli
    // dont rien ne dit ce qu'il replie.
    const { container } = render(<Vue />);
    const zone = container.querySelector(".spec-host");

    expect(screen.getByRole("button")).toHaveAttribute("aria-controls", zone?.id ?? "");
  });

  it("REVIENT replié au chargement suivant, même après avoir été déplié", () => {
    // Le renversement du 07/11/2026 : le dépliement ne se mémorise plus. Il valait pour
    // la page où on l'a fait, et la page suivante repart repliée — sans quoi le repli
    // cesse d'être un défaut pour devenir un souvenir, et l'écran revient déplié sans
    // qu'on comprenne pourquoi. Ce test tiendrait VERT sur l'ancienne mémorisation si on
    // ne vidait pas le stockage : il ne le vide pas, et c'est voulu.
    const premier = render(<Vue />);
    fireEvent.click(screen.getByRole("button"));
    expect(premier.container.querySelector(".spec-host")).not.toHaveClass("spec-folded");
    premier.unmount();

    const revenu = render(<Vue />);

    expect(screen.getByRole("button", { name: "Show the description" })).toBeInTheDocument();
    expect(revenu.container.querySelector(".spec-host")).toHaveClass("spec-folded");
  });
});
