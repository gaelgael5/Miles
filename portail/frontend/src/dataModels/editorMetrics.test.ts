import {
  FALLBACK,
  lineCount,
  metricsOf,
  offsetOfLine,
  textTopWithin,
  viewportOf,
} from "./editorMetrics";

const METRICS = { lineHeight: 20, paddingTop: 10, fontSize: 13 };

/** jsdom ne calcule aucun rectangle : on les pose, c'est la seule façon de mesurer ici. */
function boxed<T extends HTMLElement>(element: T, top: number): T {
  element.getBoundingClientRect = () => ({ top, bottom: 0, left: 0, right: 0, width: 0, height: 0, x: 0, y: top, toJSON: () => ({}) });
  return element;
}

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
  it("puts the first line exactly at the measured text top", () => {
    expect(offsetOfLine(1, 0, 17, METRICS)).toBe(17);
  });

  it("stacks the following lines by one line height each", () => {
    expect(offsetOfLine(4, 0, 17, METRICS)).toBe(77);
  });

  it("follows the scroll, and may go above the frame", () => {
    // Négatif quand la ligne est sortie par le haut : c'est au cadre de rogner, pas au
    // calcul de mentir en ramenant à zéro — la bande se collerait en haut.
    expect(offsetOfLine(2, 100, 17, METRICS)).toBe(-63);
  });
});

describe("textTopWithin", () => {
  it("counts from the content top of the box, border included", () => {
    const area = boxed(document.createElement("textarea"), 27);
    const box = boxed(document.createElement("div"), 20);
    box.style.borderTop = "1px solid black";
    document.body.append(box, area);

    // 27 (haut de la zone) + 10 (son rembourrage) - 21 (contenu de la boîte) = 16.
    expect(textTopWithin(area, box, METRICS)).toBe(16);

    box.remove();
    area.remove();
  });

  it("sees the gap a margin on the editor puts between the box and the text", () => {
    // Le défaut mesuré le 31/10/2026 : `.jslt-editor-host { margin-top: 6px }` poussait
    // le texte sans pousser la gouttière. Mesuré, l'écart se rattrape ; déduit des
    // feuilles de style, il passait inaperçu.
    const box = boxed(document.createElement("div"), 20);
    const flush = boxed(document.createElement("textarea"), 20);
    const pushed = boxed(document.createElement("textarea"), 26);
    document.body.append(box, flush, pushed);

    expect(textTopWithin(pushed, box, METRICS) - textTopWithin(flush, box, METRICS)).toBe(6);

    box.remove();
    flush.remove();
    pushed.remove();
  });

  it("falls back to the padding when nothing is laid out", () => {
    // Sous jsdom tous les rectangles valent zéro : le résultat doit rester le placement
    // d'avant toute mesure, jamais un décalage absurde.
    const area = document.createElement("textarea");
    const box = document.createElement("div");
    document.body.append(box, area);

    expect(textTopWithin(area, box, METRICS)).toBe(METRICS.paddingTop);

    box.remove();
    area.remove();
  });
});

describe("viewportOf", () => {
  it("renders nothing to bound when there is no editor yet", () => {
    expect(viewportOf(null)).toBeNull();
  });

  it("renders nothing to bound when the area has no height", () => {
    // jsdom : `offsetHeight` vaut zéro. Une gouttière haute de zéro cacherait tous les
    // numéros, ce qui serait pire que de la laisser prendre la hauteur de son contenu.
    expect(viewportOf(document.createElement("textarea"))).toBeNull();
  });

  it("renders the visible height, not the scrolled content", () => {
    // C'est le défaut du 31/10/2026 : 18 lignes de numéros sur 363px pendant que
    // l'éditeur n'en faisait que 202.
    const area = document.createElement("textarea");
    Object.defineProperty(area, "offsetHeight", { value: 202 });
    Object.defineProperty(area, "scrollHeight", { value: 371 });

    expect(viewportOf(area)).toBe(202);
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
