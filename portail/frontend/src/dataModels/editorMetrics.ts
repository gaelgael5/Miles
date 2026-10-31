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
 * Le décalage vertical d'une ligne, en pixels, dans le cadre de l'éditeur.
 *
 * Vrai parce que la zone de saisie porte `wrap="off"` : sans repli de ligne, la ligne N
 * est exactement à (N-1) hauteurs de ligne. Le jour où le composant activerait le repli,
 * ce calcul deviendrait faux pour toute ligne suivant une ligne repliée — et c'est la
 * seule hypothèse de tout ce dispositif.
 */
export function offsetOfLine(line: number, scrollTop: number, metrics: EditorMetrics): number {
  return metrics.paddingTop + (line - 1) * metrics.lineHeight - scrollTop;
}

/** Le nombre de lignes affichées : au moins une, même pour un template vide. */
export function lineCount(text: string): number {
  return text.split("\n").length;
}
