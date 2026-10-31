/**
 * Les raccourcis de l'éditeur de template, à part du composant.
 *
 * À part, et non dedans : le composant est doublé dans les tests, cette règle ne doit
 * pas l'être. La doublure et le vrai composant appellent les mêmes prédicats, donc ce
 * que les tests mesurent est ce que le navigateur exécute.
 *
 * Quand sa liste d'auto-complétion est ouverte, l'éditeur JSLT CAPTURE Tab, Entrée,
 * Échap et les flèches, et depuis urban-json-editor 0.2.0 cette liste s'ouvre dans bien
 * plus de situations (après `$`, `.`, `[`, `..`, `@.`). Ce que l'éditeur a déjà traité
 * ne se retraite donc pas côté hôte : on agirait deux fois pour une frappe.
 */
type Shortcut = {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  defaultPrevented?: boolean;
};

/** Ctrl ou Commande : l'application se tient pareil sur PC et sur Mac (Gael, 31/10/2026). */
function commanded(event: Shortcut): boolean {
  return (event.ctrlKey === true || event.metaKey === true) && event.altKey !== true;
}

/**
 * Faut-il exécuter le template sur cette frappe ? Ctrl+F5 ou ⌘F5 (Gael, 31/10/2026).
 *
 * F5 SEUL ne suffit plus : c'est le rechargement de la page dans tous les navigateurs,
 * et le capturer sur un écran privait d'un geste réflexe là où il est le plus attendu —
 * un éditeur qu'on croit figé. Avec un modificateur, la frappe est délibérée.
 */
export function runsOn(event: Shortcut): boolean {
  return event.defaultPrevented !== true && commanded(event) && event.key === "F5";
}

/**
 * Faut-il ouvrir le document source sur cette frappe ? Ctrl+Espace ou ⌘Espace.
 *
 * Remplace un bouton, retiré à la demande de Gael (31/10/2026) : on cherche un chemin
 * sans quitter le clavier ni l'endroit où l'on écrit, comme une auto-complétion. Le
 * `code` autant que la `key` : sur une disposition où Espace produit autre chose,
 * `key` ne vaut plus " ".
 */
export function opensSource(event: Shortcut & { code?: string }): boolean {
  if (event.defaultPrevented === true || !commanded(event)) {
    return false;
  }
  return event.key === " " || event.code === "Space";
}
