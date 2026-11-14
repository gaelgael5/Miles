import type { SocleSchema } from "../api/workflowEvents";

/**
 * Les noms que le moteur décrit déjà : les clefs de `properties` du socle.
 *
 * Deux autres aides vivaient ici jusqu'au 14/11/2026 — `socleClash` et `withoutSocle` —,
 * qui servaient l'éditeur de schéma d'event. Cet éditeur n'existe plus : le payload d'un
 * type d'event est un modèle ordinaire, édité par l'écran des modèles. Elles y
 * reviendront avec l'écran, pas avant : une aide que rien n'appelle ne se maintient pas.
 */
export function socleNames(socle: SocleSchema | undefined): Set<string> {
  const properties = socle?.["properties"];
  if (typeof properties !== "object" || properties === null) {
    return new Set();
  }
  return new Set(Object.keys(properties as Record<string, unknown>));
}
