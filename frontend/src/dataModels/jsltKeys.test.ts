import { runsOn } from "./jsltKeys";

describe("runsOn", () => {
  it("runs the template on F5", () => {
    expect(runsOn({ key: "F5", defaultPrevented: false })).toBe(true);
  });

  it("ignores a key the editor has already handled", () => {
    // Liste d'auto-complétion ouverte : l'éditeur capture et annule. Agir par-dessus
    // ferait deux actions pour une seule frappe.
    expect(runsOn({ key: "F5", defaultPrevented: true })).toBe(false);
  });

  it("ignores every other key", () => {
    for (const key of ["Tab", "Enter", "Escape", "ArrowDown", "a"]) {
      expect(runsOn({ key, defaultPrevented: false })).toBe(false);
    }
  });
});
