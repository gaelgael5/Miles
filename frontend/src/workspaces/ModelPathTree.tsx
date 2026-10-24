import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type ModelPath, useModelPaths } from "../api/dataModels";
import type { WorkTarget } from "../api/workTarget";

interface Node {
  path: string;
  /** Dernier segment, seul affiché : le chemin entier se lit dans l'infobulle. */
  label: string;
  kind: string;
  description: string;
  children: Node[];
}

/** Un conteneur ne se coche pas : une clé et une ligne d'index portent une seule valeur. */
export function selectable(kind: string, path: string): boolean {
  // `[0]` dit qu'on traverse un tableau : le chemin ne désignerait pas une valeur unique,
  // et le backend le refuse (`chemin_de_propriete_attendu`). On ne le propose donc pas.
  return kind !== "array" && kind !== "object" && !path.includes("[");
}

/** Dernier segment d'un chemin : « $.a.b » → « b », « $.l[0] » → « [0] ». */
export function lastSegment(path: string): string {
  const bracket = path.lastIndexOf("[");
  const dot = path.lastIndexOf(".");
  if (bracket > dot) {
    return path.slice(bracket);
  }
  return dot === -1 ? path : path.slice(dot + 1);
}

/**
 * L'arbre des propriétés d'un modèle, à partir de la liste plate que rend le serveur.
 * Un enfant arrive toujours après son parent (parcours descendant côté backend), donc
 * un seul passage suffit : on rattache chaque chemin au plus long préfixe déjà vu.
 */
export function treeOf(paths: ModelPath[]): Node[] {
  const roots: Node[] = [];
  const byPath = new Map<string, Node>();
  for (const entry of paths) {
    const node: Node = {
      path: entry.path,
      label: lastSegment(entry.path),
      kind: entry.type,
      description: entry.description,
      children: [],
    };
    byPath.set(entry.path, node);
    const parent = byPath.get(parentOf(entry.path));
    (parent ? parent.children : roots).push(node);
  }
  return roots;
}

function parentOf(path: string): string {
  const bracket = path.lastIndexOf("[");
  const dot = path.lastIndexOf(".");
  const cut = Math.max(bracket, dot);
  return cut <= 0 ? "" : path.slice(0, cut);
}

function Branch({
  node,
  selected,
  disabled,
  onToggle,
}: {
  node: Node;
  selected: string[];
  disabled: boolean;
  onToggle: (path: string) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);
  const pickable = selectable(node.kind, node.path);
  const caption = node.description === "" ? node.kind : `${node.kind} — ${node.description}`;
  return (
    <li>
      <span className="tree-row">
        {node.children.length > 0 ? (
          <button
            type="button"
            className="tree-twist"
            aria-expanded={open}
            aria-label={t(open ? "paths.collapse" : "paths.expand", { name: node.label })}
            onClick={() => setOpen(!open)}
          >
            {open ? "▾" : "▸"}
          </button>
        ) : (
          <span className="tree-twist" aria-hidden="true" />
        )}
        {pickable ? (
          <label className="tree-pick" title={node.path}>
            <input
              type="checkbox"
              disabled={disabled}
              checked={selected.includes(node.path)}
              onChange={() => onToggle(node.path)}
            />
            <span className="mono">{node.label}</span> <span className="caption">{caption}</span>
          </label>
        ) : (
          // Rendu quand même : c'est le chemin pour atteindre ses enfants.
          <span className="tree-pick muted" title={node.path}>
            <span className="mono">{node.label}</span> <span className="caption">{caption}</span>
          </span>
        )}
      </span>
      {open && node.children.length > 0 && (
        <ul className="plain-list tree">
          {node.children.map((child) => (
            <Branch
              key={child.path}
              node={child}
              selected={selected}
              disabled={disabled}
              onToggle={onToggle}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

/**
 * Choisir des propriétés d'un modèle dans un arbre plutôt que les taper (Gael, 24/10/2026).
 * Taper un jpath à la main, c'est se le faire refuser après coup pour une faute de frappe
 * ou un tableau traversé ; ici on ne peut cocher que ce que le modèle offre vraiment.
 */
export function ModelPathTree({
  target,
  model,
  selected,
  disabled,
  onToggle,
}: {
  target: WorkTarget;
  /** « portée/nom », ou chaîne vide tant qu'aucun modèle n'est choisi. */
  model: string;
  selected: string[];
  disabled: boolean;
  onToggle: (path: string) => void;
}) {
  const { t } = useTranslation();
  const [scope = null, name = null] = model === "" ? [] : model.split("/");
  const paths = useModelPaths(target, scope, name);

  if (model === "") {
    return <p className="help">{t("paths.chooseModelFirst")}</p>;
  }
  if (paths.isPending) {
    return (
      <p className="muted" role="status">
        {t("dataModels.loading")}
      </p>
    );
  }
  if (paths.isError) {
    return (
      <p className="alert" role="alert">
        {t("paths.unreadable")}
      </p>
    );
  }
  const roots = treeOf(paths.data.paths);
  if (roots.length === 0) {
    return <p className="help">{t("paths.empty")}</p>;
  }
  return (
    <ul className="plain-list tree" aria-label={t("paths.treeLabel")}>
      {roots.map((node) => (
        <Branch
          key={node.path}
          node={node}
          selected={selected}
          disabled={disabled}
          onToggle={onToggle}
        />
      ))}
    </ul>
  );
}
