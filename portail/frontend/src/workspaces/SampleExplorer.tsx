import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * Le document source de test, déplié, chaque nœud cliquable (Gael, 31/10/2026).
 *
 * Un clic met le JSONPath du nœud dans le presse-papier. C'est ce qui remplace la
 * recopie à la main d'un chemin lu dans un bloc de JSON : une faute de frappe dans
 * `$.Account[0].PickupReference` ne se voit qu'à l'exécution, et elle rend `null` sans
 * rien dire — le template reste valide.
 *
 * Le chemin est construit en DESCENDANT l'arbre, jamais recomposé depuis un libellé
 * affiché : c'est ce qui garantit qu'il désigne le nœud sur lequel on a cliqué, y
 * compris sous un indice de tableau.
 */
function childPath(path: string, key: string | number): string {
  // Notation entre crochets pour une clé qui n'est pas un identifiant simple : `$.a.b-c`
  // se lirait comme une soustraction, et `$.a["b-c"]` est la forme qui tient.
  if (typeof key === "number") {
    return `${path}[${key}]`;
  }
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(key) ? `${path}.${key}` : `${path}[${JSON.stringify(key)}]`;
}

function leafText(value: unknown): string {
  if (typeof value === "string") {
    return JSON.stringify(value);
  }
  return value === null ? "null" : String(value);
}

function Node({
  label,
  path,
  value,
  onPick,
  copied,
}: {
  label: string | null;
  path: string;
  value: unknown;
  onPick: (path: string) => void;
  copied: string | null;
}) {
  const { t } = useTranslation();
  const branch = typeof value === "object" && value !== null;
  const entries: [string | number, unknown][] = Array.isArray(value)
    ? value.map((item, index) => [index, item])
    : branch
      ? Object.entries(value as Record<string, unknown>)
      : [];
  return (
    <li className="sample-node">
      <button
        type="button"
        className={copied === path ? "sample-pick sample-picked" : "sample-pick"}
        title={t("chains.explorer.copyHelp", { path })}
        onClick={() => onPick(path)}
      >
        {label !== null && <span className="sample-key">{label}</span>}
        {branch ? (
          <span className="sample-kind">
            {Array.isArray(value)
              ? t("chains.explorer.array", { count: entries.length })
              : t("chains.explorer.object", { count: entries.length })}
          </span>
        ) : (
          <span className="sample-value mono">{leafText(value)}</span>
        )}
        {copied === path && <span className="sample-copied">{t("chains.explorer.copied")}</span>}
      </button>
      {entries.length > 0 && (
        <ul className="plain-list sample-children">
          {entries.map(([key, child]) => (
            <Node
              key={String(key)}
              label={String(key)}
              path={childPath(path, key)}
              value={child}
              onPick={onPick}
              copied={copied}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

export function SampleExplorer({ sample, onClose }: { sample: unknown; onClose: () => void }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const close = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    close.current?.focus();
  }, []);

  function pick(path: string) {
    setFailed(false);
    // Le presse-papier peut être refusé — page non sécurisée, permission retirée. On le
    // DIT et on montre le chemin : sans cela, un clic sans effet laisse croire à une
    // copie réussie, et c'est l'ancien chemin qui serait collé.
    void navigator.clipboard
      ?.writeText(path)
      .then(() => setCopied(path))
      .catch(() => {
        setCopied(null);
        setFailed(true);
      });
    if (navigator.clipboard === undefined) {
      setFailed(true);
    }
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div
        className="dialog dialog-wide"
        role="dialog"
        aria-modal="true"
        aria-label={t("chains.explorer.title")}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            onClose();
          }
        }}
      >
        <h2>{t("chains.explorer.title")}</h2>
        <p className="help">{t("chains.explorer.intro")}</p>
        {failed && (
          <p className="alert" role="alert">
            {t("chains.explorer.clipboardRefused")}
          </p>
        )}
        <ul className="plain-list sample-tree">
          <Node label={null} path="$" value={sample} onPick={pick} copied={copied} />
        </ul>
        <div className="actions">
          <button type="button" className="btn btn-secondary" ref={close} onClick={onClose}>
            {t("chains.explorer.close")}
          </button>
        </div>
      </div>
    </div>
  );
}
