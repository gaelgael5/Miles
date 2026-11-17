import type { SocleSchema } from "../api/workflowEvents";

/**
 * Les noms que le moteur décrit déjà : les clefs de `properties` du socle.
 *
 * `socleClash` est revenue le 17/11/2026 avec l'écran qui l'affiche (story `8a9ff6bc`,
 * critère 3) : le modèle d'un payload d'event se monte sous le socle VERROUILLÉ, et une
 * propriété métier qui heurte une propriété du socle doit se dire pendant la saisie. Le
 * serveur la refuse aussi (`propriete_du_socle`) — ici, c'est pour ne pas laisser écrire
 * trente champs avant de l'apprendre. `withoutSocle` n'est pas revenue : plus rien ne
 * retire le socle d'un document, le modèle ne l'a jamais porté.
 */
export function socleNames(socle: SocleSchema | undefined): Set<string> {
  const properties = socle?.["properties"];
  if (typeof properties !== "object" || properties === null) {
    return new Set();
  }
  return new Set(Object.keys(properties as Record<string, unknown>));
}


/**
 * Les propriétés MÉTIER qui heurtent une propriété du socle, par ordre d'apparition.
 *
 * Les deux schémas s'appliquent à la même propriété, et deux types incompatibles rendent
 * le payload insatisfiable sans qu'aucun des deux documents ne paraisse faux : c'est
 * pourquoi le heurt se dit, et ne se corrige pas tout seul.
 */
export function socleClash(socle: SocleSchema | undefined, schema: unknown): string[] {
  const names = socleNames(socle);
  if (names.size === 0 || typeof schema !== "object" || schema === null) {
    return [];
  }
  const properties = (schema as Record<string, unknown>)["properties"];
  if (typeof properties !== "object" || properties === null) {
    return [];
  }
  return Object.keys(properties as Record<string, unknown>).filter((name) => names.has(name));
}
