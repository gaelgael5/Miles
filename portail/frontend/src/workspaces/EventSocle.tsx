import type { SocleSchema } from "../api/workflowEvents";

/** Les noms que le moteur décrit déjà : les clefs de `properties` du socle. */
export function socleNames(socle: SocleSchema | undefined): Set<string> {
  const properties = socle?.["properties"];
  if (typeof properties !== "object" || properties === null) {
    return new Set();
  }
  return new Set(Object.keys(properties as Record<string, unknown>));
}

/** Les propriétés du schéma métier qui empiètent sur le socle, dans l'ordre du schéma.
 *
 * Montrées AVANT d'enregistrer : le serveur les refuse (`propriete_du_socle`), mais un
 * refus au moment d'enregistrer arrive après le travail. Le playground d'urban-workflow
 * fait le même signalement, pour la même raison.
 */
export function socleClash(schema: unknown, socle: SocleSchema | undefined): string[] {
  const reserved = socleNames(socle);
  if (typeof schema !== "object" || schema === null) {
    return [];
  }
  const properties = (schema as Record<string, unknown>)["properties"];
  if (typeof properties !== "object" || properties === null) {
    return [];
  }
  return Object.keys(properties as Record<string, unknown>).filter((name) => reserved.has(name));
}

/**
 * Le schéma déduit d'un échantillon, DÉBARRASSÉ des propriétés du socle, et celles
 * qu'on a retirées.
 *
 * Un échantillon réel porte le socle — `Name`, `ExternalId`, une date. Les laisser
 * déduire ferait écrire un schéma que le serveur refuse aussitôt (`propriete_du_socle`),
 * sur un geste dont la personne attend qu'il marche : ces propriétés sont décrites par le
 * moteur, pas par elle. On les retire donc, et l'écran le DIT — un retrait silencieux
 * ferait croire que l'échantillon ne les portait pas.
 */
export function withoutSocle(
  inferred: Record<string, unknown>,
  socle: SocleSchema | undefined,
): [Record<string, unknown>, string[]] {
  const reserved = socleNames(socle);
  const properties = inferred["properties"];
  if (typeof properties !== "object" || properties === null) {
    return [inferred, []];
  }
  const kept: Record<string, unknown> = {};
  const dropped: string[] = [];
  for (const [name, shape] of Object.entries(properties as Record<string, unknown>)) {
    if (reserved.has(name)) {
      dropped.push(name);
    } else {
      kept[name] = shape;
    }
  }
  const next: Record<string, unknown> = { ...inferred, properties: kept };
  const required = inferred["required"];
  if (Array.isArray(required)) {
    next["required"] = required.filter((name) => !reserved.has(String(name)));
  }
  return [next, dropped];
}
