import { useTranslation } from "react-i18next";

import type { Expiry, Index } from "../api/storages";
import { lastSegment } from "./ModelPathTree";

/**
 * Les règles de péremption d'un storage (Gael, 09/11/2026) : « on peut mettre une regle
 * sur le champs EndOfActivity + 10 jours ».
 *
 * La propriété se CHOISIT parmi les colonnes que les index déclarent, au lieu de se
 * taper ou de se cocher dans l'arbre du modèle : la règle exige une colonne réelle, et un
 * champ libre ferait écrire des règles refusées après coup — ou, pire, des règles qu'on
 * croit posées. Sans index déclaré, l'écran dit quoi faire d'abord plutôt que d'offrir un
 * bouton qui ne mène à rien.
 */
export function StorageExpiries({
  rows,
  indexes,
  disabled,
  onChange,
}: {
  rows: Expiry[];
  indexes: Index[];
  disabled: boolean;
  onChange: (rows: Expiry[]) => void;
}) {
  const { t } = useTranslation();
  // Dédoublonnées : la même colonne peut servir deux index, et elle ne se propose qu'une
  // fois. L'ordre suit la déclaration des index, celui que la personne a posé.
  const columns = [...new Set(indexes.flatMap((i) => i.columns))].filter((c) => c !== "");

  function setRow(rank: number, change: Partial<Expiry>) {
    onChange(rows.map((r, i) => (i === rank ? { ...r, ...change } : r)));
  }

  if (columns.length === 0) {
    return <p className="help">{t("storages.form.noIndexedProperty")}</p>;
  }

  return (
    <>
      <ul className="plain-list">
        {rows.map((row, rank) => (
          <li key={rank} className="index-row">
            <label className="field">
              {t("storages.fields.expiryProperty", { rank: rank + 1 })}
              <select
                required
                disabled={disabled}
                value={row.property}
                onChange={(e) => setRow(rank, { property: e.target.value })}
              >
                <option value="">{t("storages.form.choose")}</option>
                {columns.map((column) => (
                  <option key={column} value={column}>
                    {lastSegment(column)} ({column})
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              {t("storages.fields.expiryDays", { rank: rank + 1 })}
              <input
                required
                type="number"
                min={1}
                step={1}
                disabled={disabled}
                value={row.days}
                // Un champ nombre rend "" quand on efface : on retombe sur un jour plutôt
                // que sur NaN, que le contrat d'entrée refuserait sans dire quoi faire.
                onChange={(e) => setRow(rank, { days: Number(e.target.value) || 1 })}
              />
            </label>
            {/* Ce que la règle FERA, en clair : une règle de suppression qui ne dit pas
                qu'elle supprime n'est pas lisible (critère du ticket). */}
            <p className="help">
              {t("storages.form.expiryConsequence", {
                property: row.property || t("storages.form.choose"),
                count: row.days,
              })}
            </p>
            {!disabled && (
              <div className="actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => onChange(rows.filter((_, i) => i !== rank))}
                >
                  {t("storages.form.removeExpiry", { rank: rank + 1 })}
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
          onClick={() => onChange([...rows, { property: "", days: 30 }])}
        >
          {t("storages.form.addExpiry")}
        </button>
      )}
    </>
  );
}
