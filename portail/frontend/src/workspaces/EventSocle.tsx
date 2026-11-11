import { useTranslation } from "react-i18next";

import type { SocleField } from "../api/workflowEvents";

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
  socle: SocleField[],
): [Record<string, unknown>, string[]] {
  const reserved = new Set(socle.map((f) => f.name));
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

/** Le socle commun, tel que le MOTEUR le valide : montré, jamais modifiable. */
export function SocleTable({ socle }: { socle: SocleField[] }) {
  const { t } = useTranslation();
  return (
    <div className="card">
      <h2>{t("workflowEvents.socle.title")}</h2>
      <p className="help">{t("workflowEvents.socle.help")}</p>
      <ul className="plain-list">
        {socle.map((field) => (
          <li key={field.name} className="row">
            <div className="row-main">
              <span className="mono">{field.name}</span> <span className="muted">{field.type}</span>
            </div>
            {field.read_only && (
              <span className="badge badge-muted">{t("workflowEvents.socle.posed")}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
