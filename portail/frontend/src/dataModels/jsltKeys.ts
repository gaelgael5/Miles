/**
 * Faut-il exécuter le template sur cette frappe ?
 *
 * Quand sa liste d'auto-complétion est ouverte, l'éditeur JSLT CAPTURE Tab, Entrée,
 * Échap et les flèches, et depuis urban-json-editor 0.2.0 cette liste s'ouvre dans bien
 * plus de situations (après `$`, `.`, `[`, `..`, `@.`). Ce que l'éditeur a déjà traité
 * ne se retraite donc pas côté hôte : on agirait deux fois pour une frappe. F5 n'est pas
 * capturé aujourd'hui, mais la règle vaut pour tout raccourci qu'on ajouterait.
 *
 * À part du composant, et non dedans : le composant est doublé dans les tests, cette
 * règle ne doit pas l'être.
 */
export function runsOn(event: { key: string; defaultPrevented: boolean }): boolean {
  return !event.defaultPrevented && event.key === "F5";
}
