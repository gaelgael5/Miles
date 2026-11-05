import { fireEvent, render, screen } from "@testing-library/react";

import "../i18n/i18n";
import { Topbar } from "./Topbar";
import { NAV_ID, useSidebar } from "./useSidebar";

/** L'ossature d'un back-office : la barre et le menu qu'elle commande. */
function Shell() {
  const sidebar = useSidebar();
  return (
    <>
      <Topbar sidebar={sidebar} />
      <nav id={NAV_ID} className={sidebar.navClassName} aria-label="Main navigation">
        <button type="button">Secrets</button>
      </nav>
    </>
  );
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("le repli du menu", () => {
  it("replie et déplie le menu, et le dit sur le bouton", () => {
    render(<Shell />);
    const bouton = screen.getByRole("button", { name: "Collapse or expand the menu" });
    expect(bouton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("navigation")).toHaveClass("sidebar");
    expect(screen.getByRole("navigation")).not.toHaveClass("sidebar-collapsed");

    fireEvent.click(bouton);

    expect(bouton).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("navigation")).toHaveClass("sidebar-collapsed");
  });

  it("désigne le menu qu'il commande", () => {
    // Sans ce lien, le bouton annonce un état — replié, déplié — sans dire de QUOI.
    render(<Shell />);

    const bouton = screen.getByRole("button", { name: "Collapse or expand the menu" });
    expect(bouton).toHaveAttribute("aria-controls", screen.getByRole("navigation").id);
  });

  it("garde le choix d'une page à l'autre", () => {
    // Qui replie le menu travaille à l'étroit : le redéplier à chaque rechargement
    // défait le geste à chaque fois.
    const premiere = render(<Shell />);
    fireEvent.click(screen.getByRole("button", { name: "Collapse or expand the menu" }));
    premiere.unmount();

    render(<Shell />);

    expect(screen.getByRole("navigation")).toHaveClass("sidebar-collapsed");
  });

  it("n'offre aucun bouton là où il n'y a pas de menu", () => {
    // L'amorçage et la connexion n'ont pas de navigation : un bouton qui ne commande
    // rien se lit comme une panne.
    render(<Topbar />);

    expect(screen.queryByRole("button", { name: "Collapse or expand the menu" })).toBeNull();
  });

  it("s'ouvre déplié quand le navigateur refuse de mémoriser", () => {
    // Navigation privée, stockage refusé : le menu s'affiche, plutôt qu'une page sans
    // navigation dont rien ne dirait pourquoi.
    const refuse = () => {
      throw new Error("stockage refusé");
    };
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(refuse);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(refuse);

    render(<Shell />);
    fireEvent.click(screen.getByRole("button", { name: "Collapse or expand the menu" }));

    expect(screen.getByRole("navigation")).toHaveClass("sidebar-collapsed");
    vi.restoreAllMocks();
  });
});
