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
 * Faut-il ouvrir le document source sur cette frappe ? Ctrl+point ou ⌘point.
 *
 * Remplace un bouton, retiré à la demande de Gael (31/10/2026) : on cherche un chemin
 * sans quitter le clavier ni l'endroit où l'on écrit, comme une auto-complétion.
 *
 * L'Espace, posé le même jour, ne peut pas être tenu : macOS prend ⌘Espace pour
 * Spotlight AVANT le navigateur — la frappe n'atteint jamais la page, et aucun code de
 * l'hôte ne la rattrape —, et Ctrl+Espace y change la source de saisie dès qu'il y en a
 * deux. Le point le remplace (Gael, 01/11/2026) : c'est le geste « action rapide » des
 * éditeurs, et le système le laisse passer.
 *
 * Le `code` autant que la `key`, et ici pour une raison précise : sur un clavier AZERTY
 * le point demande Maj, et c'est la MÊME touche physique (`Period`) qui donne « ; »
 * sans Maj. L'accepter par son code sert les deux dispositions sans exiger une Maj qui
 * n'a de sens sur aucune des deux.
 */
export function opensSource(event: Shortcut & { code?: string }): boolean {
  if (event.defaultPrevented === true || !commanded(event)) {
    return false;
  }
  return event.key === "." || event.code === "Period";
}
