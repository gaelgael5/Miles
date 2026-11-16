import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import type { BrokenModelRef, ModelUsage } from "../api/dataModels";

/**
 * À quoi sert un modèle : ce qui le DÉSIGNE, et rien d'autre.
 *
 * Un seul fichier porte ce vocabulaire — le résumé d'une ligne de la liste et le détail
 * de l'écran d'un modèle. Nommé à deux endroits, « type d'event » l'aurait été de deux
 * façons, et c'est justement de nommer qu'il s'agit ici.
 */

/** Les natures, DANS L'ORDRE où on les montre : du plus parlant au plus technique. */
const KINDS: string[] = ["event_type", "storage", "source", "chain_step", "model"];

function kindLabel(t: TFunction, kind: string): string {
  // `defaultValue` : une nature que le serveur ajoute — un état de workflow viendra avec
  // la feature d1f2e043 — s'affiche sous son code plutôt que sous une clef de traduction.
  return t(`dataModels.role.kinds.${kind}`, { defaultValue: kind });
}

/** « 2 types d'event · 1 storage » — ce que la ligne de la liste montre. */
export function roleSummary(t: TFunction, usages: ModelUsage[]): string {
  const counted = new Map<string, number>();
  for (const usage of usages) {
    counted.set(usage.kind, (counted.get(usage.kind) ?? 0) + 1);
  }
  const unknown = [...counted.keys()].filter((kind) => !KINDS.includes(kind));
  return [...KINDS.filter((kind) => counted.has(kind)), ...unknown]
    .map((kind) => {
      const count = counted.get(kind) ?? 0;
      return t(`dataModels.role.counts.${kind}`, {
        count,
        defaultValue: `${count} × ${kindLabel(t, kind)}`,
      });
    })
    .join(" · ");
}

function usageKey(usage: ModelUsage): string {
  return `${usage.kind}/${usage.path}/${usage.name}/${usage.part ?? ""}`;
}

/** Une désignation, nommément : sa nature, son nom, et le fichier qui la porte. */
function UsageRow({ usage, onOpen }: { usage: ModelUsage; onOpen?: () => void }) {
  const { t } = useTranslation();
  return (
    <li className={onOpen ? "row row-openable" : "row"}>
      <div className="row-main">
        {/* Toute la ligne ouvre le désignateur, comme partout ailleurs dans le portail
            (story fbe9b512). Sans navigation possible, c'est un titre, pas un bouton :
            une ligne qui s'ouvre sur rien promettrait un geste qui n'existe pas. */}
        {onOpen ? (
          <button type="button" className="row-title row-open" onClick={onOpen}>
            {usage.label ?? usage.name}
          </button>
        ) : (
          <div className="row-title">{usage.label ?? usage.name}</div>
        )}
        <div className="row-sub mono">
          {usage.name}
          {usage.part !== null ? ` · ${usage.part}` : ""} · {usage.path}
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("dataModels.role.caption")}</div>
        <div className="value">{kindLabel(t, usage.kind)}</div>
      </div>
    </li>
  );
}

/**
 * Ce qui désigne ce modèle, et ce que lui-même ne trouve plus.
 *
 * Les deux sens ensemble, exprès : on ouvre cette vue AVANT de changer un modèle, et ce
 * qu'il faut savoir alors est à la fois qui en dépend et ce qui lui manque.
 */
export function ModelRole({
  usages,
  broken,
  onOpen,
}: {
  usages: ModelUsage[];
  broken: BrokenModelRef[];
  onOpen?: (usage: ModelUsage) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="card" role="region" aria-label={t("dataModels.role.title")}>
      <h2>{t("dataModels.role.title")}</h2>
      <p className="help">{t("dataModels.role.intro")}</p>
      {usages.length === 0 ? (
        <p className="muted">{t("dataModels.role.empty")}</p>
      ) : (
        <ul className="card-list plain-list">
          {usages.map((usage) => (
            <UsageRow
              key={usageKey(usage)}
              usage={usage}
              onOpen={onOpen === undefined ? undefined : () => onOpen(usage)}
            />
          ))}
        </ul>
      )}
      {broken.length > 0 && <BrokenRefs broken={broken} />}
    </div>
  );
}

/** Les désignations dont la cible manque : dites ici, et non seulement au figement. */
export function BrokenRefs({ broken }: { broken: BrokenModelRef[] }) {
  const { t } = useTranslation();
  return (
    <div className="notice" role="note">
      <p>{t("dataModels.role.broken.title")}</p>
      <ul>
        {broken.map((ref) => (
          <li key={`${usageKey(ref)}/${ref.target}`}>
            {t("dataModels.role.broken.line", {
              what: kindLabel(t, ref.kind),
              name: ref.name,
              target: ref.target,
              path: ref.path,
            })}
          </li>
        ))}
      </ul>
      <p className="help">{t("dataModels.role.broken.intro")}</p>
    </div>
  );
}
