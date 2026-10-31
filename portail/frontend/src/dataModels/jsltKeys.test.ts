import { opensSource, runsOn } from "./jsltKeys";

describe("runsOn", () => {
  it("runs the template on Ctrl+F5 and on Command+F5", () => {
    expect(runsOn({ key: "F5", ctrlKey: true })).toBe(true);
    // ⌘F5 : l'application se tient pareil sur PC et sur Mac (Gael, 31/10/2026).
    expect(runsOn({ key: "F5", metaKey: true })).toBe(true);
  });

  it("leaves a bare F5 to the browser", () => {
    // F5 seul recharge la page, dans tous les navigateurs. Le capturer privait d'un
    // geste réflexe exactement là où on en a le plus envie : un éditeur qui semble figé.
    expect(runsOn({ key: "F5" })).toBe(false);
  });

  it("ignores a key the editor has already handled", () => {
    // Liste d'auto-complétion ouverte : l'éditeur capture et annule. Agir par-dessus
    // ferait deux actions pour une seule frappe.
    expect(runsOn({ key: "F5", ctrlKey: true, defaultPrevented: true })).toBe(false);
  });

  it("ignores Alt, which is another shortcut entirely", () => {
    expect(runsOn({ key: "F5", ctrlKey: true, altKey: true })).toBe(false);
  });

  it("ignores every other key", () => {
    for (const key of ["Tab", "Enter", "Escape", "ArrowDown", "a"]) {
      expect(runsOn({ key, ctrlKey: true })).toBe(false);
    }
  });
});

describe("opensSource", () => {
  it("opens the source document on Ctrl+Space and on Command+Space", () => {
    expect(opensSource({ key: " ", ctrlKey: true })).toBe(true);
    expect(opensSource({ key: " ", metaKey: true })).toBe(true);
  });

  it("reads the physical key too, for a layout where Space produces something else", () => {
    expect(opensSource({ key: "Unidentified", code: "Space", ctrlKey: true })).toBe(true);
  });

  it("leaves a bare Space alone, which is just typing", () => {
    expect(opensSource({ key: " " })).toBe(false);
  });

  it("ignores a key the editor has already handled", () => {
    expect(opensSource({ key: " ", ctrlKey: true, defaultPrevented: true })).toBe(false);
  });
});
