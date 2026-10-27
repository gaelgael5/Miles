import { useTranslation } from "react-i18next";

import { type Index, MAX_COLUMNS } from "../api/storages";
import type { WorkTarget } from "../api/workTarget";
import { PathPicker, lastSegment } from "./ModelPathTree";

/** Nom d'index proposé, jamais en doublon d'un existant ni refusé par la règle de nommage. */
export function indexName(taken: string[]): string {
  for (let n = 1; n < 100; n += 1) {
    if (!taken.includes(`index-${n}`)) {
      return `index-${n}`;
    }
  }
  return "index";
}

/** Ce que le champ d'un index affiche fermé : ses colonnes, dans l'ordre. */
export function columnsSummary(columns: string[], empty: string): string {
  return columns.length === 0 ? empty : columns.map(lastSegment).join(" · ");
}

/**
 * Les index additionnels d'un storage (Gael, 24/10/2026) : « l'utilisateur ajoute un
 * index et après il choisit les colonnes », autant d'index que nécessaire, trois colonnes
 * au plus chacun.
 *
 * L'ordre des colonnes est celui de l'index composite : il sert les filtres sur la
 * première colonne, puis sur les deux premières, etc. On ajoute donc à la fin, et on ne
 * réordonne pas dans le dos de la personne.
 */
export function StorageIndexes({
  target,
  model,
  rows,
  disabled,
  onChange,
}: {
  target: WorkTarget;
  model: string;
  rows: Index[];
  disabled: boolean;
  onChange: (rows: Index[]) => void;
}) {
  const { t } = useTranslation();

  function setRow(rank: number, change: Partial<Index>) {
    onChange(rows.map((r, i) => (i === rank ? { ...r, ...change } : r)));
  }

  function toggleColumn(rank: number, path: string) {
    const row = rows[rank];
    if (row === undefined) {
      return;
    }
    if (row.columns.includes(path)) {
      setRow(rank, { columns: row.columns.filter((c) => c !== path) });
    } else if (row.columns.length < MAX_COLUMNS) {
      // Au-delà du plafond, l'arbre grise déjà les cases : cette garde est la seconde,
      // pour que la règle tienne même si l'écran change.
      setRow(rank, { columns: [...row.columns, path] });
    }
  }

  return (
    <>
      <ul className="plain-list">
        {rows.map((row, rank) => (
          <li key={rank} className="index-row">
            <label className="field">
              {t("storages.fields.indexName", { rank: rank + 1 })}
              <input
                required
                disabled={disabled}
                value={row.name}
                onChange={(e) => setRow(rank, { name: e.target.value })}
              />
            </label>
            <div className="index-columns">
              <span className="caption">
                {t("storages.fields.indexColumns", {
                  rank: rank + 1,
                  count: row.columns.length,
                  max: MAX_COLUMNS,
                })}
              </span>
              <PathPicker
                target={target}
                model={model}
                selected={row.columns}
                disabled={disabled}
                atMax={row.columns.length >= MAX_COLUMNS}
                label={t("storages.fields.indexColumnsLabel", { name: row.name })}
                summary={columnsSummary(row.columns, t("storages.form.noColumn"))}
                onToggle={(path) => toggleColumn(rank, path)}
              />
            </div>
            {!disabled && (
              <div className="actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => onChange(rows.filter((_, i) => i !== rank))}
                >
                  {t("storages.form.removeIndex", { rank: rank + 1 })}
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {!disabled && (
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() =>
            onChange([...rows, { name: indexName(rows.map((r) => r.name)), columns: [] }])
          }
        >
          {t("storages.form.addIndex")}
        </button>
      )}
    </>
  );
}
