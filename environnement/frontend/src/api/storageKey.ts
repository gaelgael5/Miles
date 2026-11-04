/**
 * La clé fonctionnelle d'un objet : ce que la base porte, ce qu'on lit, ce qu'on cherche.
 *
 * La base la porte sous sa forme CANONIQUE — un tableau JSON compact, `["S-001"]`, même
 * pour une clé d'une seule partie (`ingestion/keys.py`, `key_of`). Cette forme est la
 * bonne : elle ne change pas le jour où un storage gagne une seconde partie de clé, et
 * deux clés « a|b » et « a », « b » ne peuvent pas s'y confondre.
 *
 * Mais elle ne se LIT pas, et elle ne se TAPE pas : l'écran montrait `["S-001"]` et ne
 * trouvait rien sur `S-001` (Gael, 04/11/2026 : « le filtre ne fonctionne pas »). Ce
 * module tient donc les deux sens — afficher les parties, recomposer la forme canonique
 * — en UN endroit, parce que le jour où l'encodage du serveur change, c'est ici qu'il
 * faut suivre et nulle part ailleurs.
 */
export const KEY_COLUMN = "cle";

/** Les parties de la clé. Une clé illisible est rendue telle quelle, jamais perdue. */
export function keyParts(cle: string): string[] {
  try {
    const lu: unknown = JSON.parse(cle);
    return Array.isArray(lu) ? lu.map((partie) => String(partie)) : [cle];
  } catch {
    // Une clé écrite avant cette forme, ou par un autre chemin : on l'affiche telle
    // quelle plutôt que de rendre une ligne sans identité.
    return [cle];
  }
}

/** La clé telle qu'on la lit : ses parties, dans l'ordre où le paramétrage les déclare. */
export function readableKey(cle: string): string {
  return keyParts(cle).join(" · ");
}

/**
 * La valeur à comparer à la colonne de clé, pour ce qui a été tapé.
 *
 * « contient » et « commence par » cherchent DANS la forme canonique : `S-001` y est tel
 * quel, et c'est ce qui fait que l'opérateur par défaut de l'écran trouve ce qu'on lui
 * demande sans rien recomposer. « égale », lui, compare la chaîne entière et exige donc
 * la forme canonique — `JSON.stringify` produit exactement ce que
 * `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` produit côté serveur.
 *
 * L'écran n'offre « égale » sur la clé que lorsqu'elle n'a qu'UNE partie : avec
 * plusieurs, une seule valeur saisie ne peut pas dire laquelle, et composer un tableau
 * d'une valeur ne trouverait jamais rien.
 */
export function encodedKey(value: string, operator: string): string {
  return operator === "eq" || operator === "ne" ? JSON.stringify([value]) : value;
}
