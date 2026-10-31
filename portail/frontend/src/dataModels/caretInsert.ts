/** Où insérer, et quoi, dans un texte — sans toucher au DOM, donc mesurable. */
export interface Caret {
  start: number;
  end: number;
}

/**
 * Le texte avec `inserted` posé à la place de la sélection (ou au curseur si elle est
 * vide), et la position du curseur APRÈS l'insertion.
 *
 * Rendue plutôt qu'appliquée : l'éditeur réel est un Web Component dont la valeur est
 * tenue par React. Écrire dans son `<textarea>` interne poserait le texte sans que la
 * couche de coloration ni l'état de l'écran ne le sachent — le template aurait l'air
 * d'avoir changé et serait enregistré sans le chemin.
 */
export function withInsertion(
  text: string,
  inserted: string,
  caret: Caret | null,
): { text: string; caret: number } {
  // Curseur inconnu : on ajoute à la fin plutôt que d'écraser le début. Perdre le
  // curseur ne doit jamais faire perdre ce qui est écrit.
  const at = caret ?? { start: text.length, end: text.length };
  const start = Math.min(Math.max(at.start, 0), text.length);
  const end = Math.min(Math.max(at.end, start), text.length);
  return {
    text: text.slice(0, start) + inserted + text.slice(end),
    caret: start + inserted.length,
  };
}

/** Le curseur de la zone de saisie de l'éditeur, réelle ou doublée : même `<textarea>`. */
export function caretOf(host: HTMLElement | null): Caret | null {
  const area = host?.querySelector("textarea");
  return area === null || area === undefined
    ? null
    : { start: area.selectionStart, end: area.selectionEnd };
}

export function placeCaret(host: HTMLElement | null, at: number): void {
  const area = host?.querySelector("textarea");
  area?.focus();
  area?.setSelectionRange(at, at);
}
