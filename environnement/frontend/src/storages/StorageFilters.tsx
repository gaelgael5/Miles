import { useTranslation } from "react-i18next";

import { type Criterion, OPERATORS, type Storage } from "../api/storages";

/** La colonne de la clé fonctionnelle : filtrable comme les autres, et nommée à part. */
export const KEY_COLUMN = "cle";

/**
 * Ce sur quoi on peut filtrer un storage, et c'est le paramétrage qui le dit : sa clé
 * fonctionnelle, et les colonnes de ses index déclarés.
 *
 * **Rien d'autre n'est offert, et c'est délibéré.** Le serveur refuse un critère sur une
 * propriété non déclarée plutôt que de parcourir la table ; offrir ici un champ libre
 * ferait découvrir ce refus après coup, alors qu'on peut ne proposer que ce qui marche.
 * C'est la même règle que l'arbre des propriétés du portail : on ne coche que ce que le
 * modèle offre vraiment.
 */
export function filterable(storage: Storage): { column: string; label: string }[] {
  const colonnes = storage.indexes.flatMap((index) => index.columns);
  const vues = new Set<string>();
  const offertes = [{ column: KEY_COLUMN, label: storage.keys.join(" · ") }];
  for (const colonne of colonnes) {
    if (vues.has(colonne)) {
      continue;
    }
    vues.add(colonne);
    // Le chemin DÉCLARÉ comme libellé, jamais le nom de colonne dérivé : c'est sous ce
    // chemin que la personne a choisi la propriété, et « contact_phone » ne lui dirait
    // pas lequel de ses index elle interroge.
    const projection = storage.projections.find((p) => p.column === colonne);
    offertes.push({ column: colonne, label: projection?.path ?? colonne });
  }
  return offertes;
}

export function StorageFilters({
  storage,
  criteria,
  onChange,
}: {
  storage: Storage;
  criteria: Criterion[];
  onChange: (criteria: Criterion[]) => void;
}) {
  const { t } = useTranslation();
  const offertes = filterable(storage);

  function modifie(rank: number, change: Partial<Criterion>) {
    onChange(criteria.map((c, i) => (i === rank ? { ...c, ...change } : c)));
  }

  return (
    <form
      className="panel"
      aria-label={t("storages.filters.title")}
      onSubmit={(event) => event.preventDefault()}
    >
      <ul className="plain-list">
        {criteria.map((critere, rank) => (
          <li key={rank} className="index-row">
            <label className="field">
              {t("storages.filters.property")}
              <select
                value={critere.column}
                onChange={(e) => modifie(rank, { column: e.target.value })}
              >
                <option value="">{t("storages.filters.choose")}</option>
                {offertes.map((offerte) => (
                  <option key={offerte.column} value={offerte.column}>
                    {offerte.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              {t("storages.filters.operator")}
              <select
                value={critere.operator}
                onChange={(e) => modifie(rank, { operator: e.target.value })}
              >
                {OPERATORS.map((operateur) => (
                  <option key={operateur} value={operateur}>
                    {t(`storages.operators.${operateur}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              {t("storages.filters.value")}
              <input
                value={critere.value}
                onChange={(e) => modifie(rank, { value: e.target.value })}
              />
            </label>
            <div className="actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => onChange(criteria.filter((_, i) => i !== rank))}
              >
                {t("storages.filters.remove", { rank: rank + 1 })}
              </button>
            </div>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="btn btn-secondary"
        onClick={() => onChange([...criteria, { column: "", operator: "eq", value: "" }])}
      >
        {t("storages.filters.add")}
      </button>
    </form>
  );
}
