import { FALLBACK, lineCount, metricsOf, offsetOfLine } from "./editorMetrics";

describe("lineCount", () => {
  it("counts one line for an empty template", () => {
    // Zéro ligne n'afficherait aucun numéro devant un curseur qui, lui, est bien là.
    expect(lineCount("")).toBe(1);
  });

  it("counts the line after a trailing newline", () => {
    expect(lineCount("a\nb\n")).toBe(3);
  });
});

describe("offsetOfLine", () => {
  it("puts the first line right under the padding", () => {
    expect(offsetOfLine(1, 0, { lineHeight: 20, paddingTop: 10, fontSize: 13 })).toBe(10);
  });

  it("stacks the following lines by one line height each", () => {
    expect(offsetOfLine(4, 0, { lineHeight: 20, paddingTop: 10, fontSize: 13 })).toBe(70);
  });

  it("follows the scroll, and may go above the frame", () => {
    // Négatif quand la ligne est sortie par le haut : c'est au cadre de rogner, pas au
    // calcul de mentir en ramenant à zéro — la bande se collerait en haut.
    expect(offsetOfLine(2, 100, { lineHeight: 20, paddingTop: 10, fontSize: 13 })).toBe(-70);
  });
});

describe("metricsOf", () => {
  it("falls back when there is nothing to measure", () => {
    // Sous jsdom, `getComputedStyle` ne calcule rien : sans repli, tout tomberait à
    // zéro et les numéros se superposeraient sur une seule ligne.
    expect(metricsOf(null)).toEqual(FALLBACK);
  });

  it("falls back on a line height that is not a number of pixels", () => {
    const area = document.createElement("textarea");
    area.style.lineHeight = "normal";
    document.body.append(area);

    expect(metricsOf(area).lineHeight).toBe(FALLBACK.lineHeight);

    area.remove();
  });
});
