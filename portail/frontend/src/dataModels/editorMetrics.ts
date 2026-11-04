/**
 * Les mesures dont la gouttière et le surlignement ont besoin, lues sur la zone de
 * saisie elle-même.
 *
 * Lues et non recopiées : la hauteur de ligne et le rembourrage viennent de la feuille
 * de style du composant (`urban-json-editor`), que Miles sert mais n'écrit pas. Les
 * figer ici ferait glisser les numéros d'un pixel par ligne à la première mise à jour
 * du composant, et l'écart ne se verrait qu'en bas d'un long template.
 *
 * Les valeurs de repli sont celles de la feuille actuelle (13px × 1.5, 10px de
 * rembourrage) : sous jsdom, `getComputedStyle` ne calcule rien, et un `NaN` placerait
 * tout à zéro au lieu de placer approximativement.
 */
export interface EditorMetrics {
  lineHeight: number;
  paddingTop: number;
  fontSize: number;
}

export const FALLBACK: EditorMetrics = { lineHeight: 19.5, paddingTop: 10, fontSize: 13 };

function pixels(value: string, fallback: number): number {
  const read = Number.parseFloat(value);
  return Number.isFinite(read) && read > 0 ? read : fallback;
}

/** Comme `pixels`, mais zéro est une valeur LÉGITIME : une bordure peut être absente. */
function edge(value: string): number {
  const read = Number.parseFloat(value);
  return Number.isFinite(read) && read > 0 ? read : 0;
}

export function metricsOf(area: HTMLTextAreaElement | null): EditorMetrics {
  if (area === null) {
    return FALLBACK;
  }
  const style = getComputedStyle(area);
  return {
    // « normal » n'est pas un nombre de pixels : `parseFloat` rend NaN, et le repli joue.
    lineHeight: pixels(style.lineHeight, FALLBACK.lineHeight),
    paddingTop: pixels(style.paddingTop, FALLBACK.paddingTop),
    // La taille aussi : un numéro de ligne d'une autre taille que son texte se décale
    // à la verticale, et l'écart grandit à chaque ligne.
    fontSize: pixels(style.fontSize, FALLBACK.fontSize),
  };
}

/**
 * Le haut du TEXTE de la zone de saisie, compté depuis le haut du contenu de `box`.
 *
 * Mesuré et non déduit : entre le cadre et le texte s'empilent des épaisseurs qui
 * n'appartiennent pas à Miles — la bordure du composant, et tout retrait que sa feuille
 * ou celle du socle poseraient autour de lui. Les additionner à la main revient à tenir
 * une copie de feuilles de style qu'on n'écrit pas : c'est exactement ce qui a mis le
 * texte 6px sous ses numéros (`.jslt-editor-host { margin-top: 6px }` du socle, mesuré
 * au pixel sur la capture de Gael, 31/10/2026).
 *
 * Sous jsdom, tous les rectangles valent zéro et le résultat vaut le rembourrage : la
 * même chose qu'avant toute mesure, donc jamais un placement absurde.
 */
export function textTopWithin(
  area: HTMLTextAreaElement,
  box: HTMLElement,
  metrics: EditorMetrics,
): number {
  const style = getComputedStyle(box);
  const content = box.getBoundingClientRect().top + edge(style.borderTopWidth) + edge(style.paddingTop);
  return area.getBoundingClientRect().top + metrics.paddingTop - content;
}

/**
 * La hauteur VISIBLE de la zone de saisie, bordures comprises ; `null` si rien n'est
 * mesurable (jsdom, ou composant pas encore posé).
 *
 * C'est elle qui borne la gouttière. Sans borne, la gouttière est aussi haute que son
 * nombre de lignes : elle devient l'élément le plus haut de l'assemblage, et les
 * numéros descendent bien au-dessous du cadre de l'éditeur — mesuré, 363px de numéros
 * contre 202px d'éditeur pour un template de 18 lignes.
 */
export function viewportOf(area: HTMLTextAreaElement | null): number | null {
  if (area === null || area.offsetHeight <= 0) {
    return null;
  }
  return area.offsetHeight;
}

/**
 * Le décalage vertical d'une ligne, en pixels, depuis le haut du cadre de l'éditeur.
 *
 * Vrai parce que la zone de saisie porte `wrap="off"` : sans repli de ligne, la ligne N
 * est exactement à (N-1) hauteurs de ligne. Le jour où le composant activerait le repli,
 * ce calcul deviendrait faux pour toute ligne suivant une ligne repliée — et c'est la
 * seule hypothèse de tout ce dispositif.
 */
export function offsetOfLine(
  line: number,
  scrollTop: number,
  textTop: number,
  metrics: EditorMetrics,
): number {
  return textTop + (line - 1) * metrics.lineHeight - scrollTop;
}

/** Le nombre de lignes affichées : au moins une, même pour un template vide. */
export function lineCount(text: string): number {
  return text.split("\n").length;
}
