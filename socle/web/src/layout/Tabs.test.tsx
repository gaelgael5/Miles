import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";

import { Tabs } from "./Tabs";

const ONGLETS = [
  { name: "contract", label: "Contract" },
  { name: "trial", label: "Trial" },
  { name: "calls", label: "Call log" },
] as const;

function Page() {
  const [onglet, setOnglet] = useState<(typeof ONGLETS)[number]["name"]>("contract");
  return (
    <Tabs label="Source views" tabs={ONGLETS} current={onglet} onSelect={setOnglet}>
      <p>{`contenu de ${onglet}`}</p>
    </Tabs>
  );
}

describe("Tabs", () => {
  it("ne montre que le panneau de l'onglet choisi", () => {
    render(<Page />);
    expect(screen.getByText("contenu de contract")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Call log" }));

    expect(screen.getByText("contenu de calls")).toBeInTheDocument();
    expect(screen.queryByText("contenu de contract")).not.toBeInTheDocument();
  });

  it("lie le panneau à son onglet, dans les deux sens", () => {
    // C'est ce lien qui fait qu'un lecteur d'écran annonce le panneau sous le nom de
    // l'onglet, et l'onglet comme commandant ce panneau. Deux chaînes composées à la
    // main par l'appelant auraient divergé sans que rien ne rougisse.
    render(<Page />);

    const onglet = screen.getByRole("tab", { name: "Contract" });
    const panneau = screen.getByRole("tabpanel");
    expect(onglet).toHaveAttribute("aria-controls", panneau.id);
    expect(panneau).toHaveAttribute("aria-labelledby", onglet.id);
  });

  it("n'offre qu'une entrée au clavier, et les flèches pour changer d'onglet", () => {
    // Sans le tabindex mobile, la tabulation traverse chaque onglet avant d'atteindre
    // le contenu de la page.
    render(<Page />);
    const barre = screen.getAllByRole("tab");
    expect(barre.map((bouton) => bouton.tabIndex)).toEqual([0, -1, -1]);

    fireEvent.keyDown(screen.getByRole("tab", { name: "Contract" }), { key: "ArrowRight" });

    expect(screen.getByRole("tab", { name: "Trial" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Trial" })).toHaveFocus();
  });

  it("revient au dernier onglet par la flèche gauche depuis le premier", () => {
    // La barre boucle : c'est ce que le motif ARIA décrit, et l'arrêt au bord laisse
    // croire que la flèche ne fait rien.
    render(<Page />);

    fireEvent.keyDown(screen.getByRole("tab", { name: "Contract" }), { key: "ArrowLeft" });

    expect(screen.getByRole("tab", { name: "Call log" })).toHaveAttribute("aria-selected", "true");
  });

  it("laisse passer les autres touches", () => {
    render(<Page />);

    fireEvent.keyDown(screen.getByRole("tab", { name: "Contract" }), { key: "a" });

    expect(screen.getByRole("tab", { name: "Contract" })).toHaveAttribute("aria-selected", "true");
  });
});
