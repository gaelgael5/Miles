import { useTranslation } from "react-i18next";

import { KEY_COLUMN } from "../api/storageKey";
import { type Criterion, type Storage, operatorsFor } from "../api/storages";

/** Une propriété sur laquelle on peut filtrer : sa colonne, son libellé, son type SQL. */
export interface Filterable {
  column: string;
  label: string;
  sqlType: string;
}

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
export function filterable(storage: Storage): Filterable[] {
  const colonnes = storage.indexes.flatMap((index) => index.columns);
  const vues = new Set<string>();
  // La clé est du TEXTE en base, quelles que soient les valeurs qui la composent : elle
  // y est rangée sous sa forme canonique, un tableau JSON.
  const offertes: Filterable[] = [
    { column: KEY_COLUMN, label: storage.keys.join(" · "), sqlType: "text" },
  ];
  for (const colonne of colonnes) {
    if (vues.has(colonne)) {
      continue;
    }
    vues.add(colonne);
    // Le chemin DÉCLARÉ comme libellé, jamais le nom de colonne dérivé : c'est sous ce
    // chemin que la personne a choisi la propriété, et « contact_phone » ne lui dirait
    // pas lequel de ses index elle interroge.
    const projection = storage.projections.find((p) => p.column === colonne);
    offertes.push({
      column: colonne,
      label: projection?.path ?? colonne,
      sqlType: projection?.sql_type ?? "text",
    });
  }
  return offertes;
}

/**
 * Les comparaisons offertes sur une propriété. Sur la CLÉ à plusieurs parties, « égale »
 * est retiré : une seule valeur saisie ne peut pas dire de quelle partie il s'agit, et
 * composer un tableau d'une valeur ne trouverait jamais rien (voir `storageKey`).
 */
function operators(storage: Storage, offerte: Filterable): readonly string[] {
  const offerts = operatorsFor(offerte.sqlType);
  if (offerte.column !== KEY_COLUMN || storage.keys.length <= 1) {
    return offerts;
  }
  return offerts.filter((operateur) => operateur !== "eq" && operateur !== "ne");
}

/** Un critère vide par propriété filtrable, chacun sur sa comparaison par défaut. */
export function emptyCriteria(storage: Storage): Criterion[] {
  return filterable(storage).map((offerte) => ({
    column: offerte.column,
    operator: operators(storage, offerte)[0] ?? "eq",
    value: "",
  }));
}

/**
 * La barre de filtres : UNE colonne par propriété filtrable (Gael, 04/11/2026).
 *
 * Remplace la liste de critères qu'on ajoutait un à un. Celle-ci ouvrait sur « choisir
 * une propriété » et laissait taper une valeur sans en choisir aucune : le critère était
 * alors silencieusement ignoré, et l'écran montrait tous les objets comme s'il avait
 * filtré. Avec une colonne par propriété, il n'y a plus de critère incomplet à ignorer.
 *
 * La forme — un bandeau de champs au-dessus de la table — est celle de la maquette
 * « Référentiel de comptes » du cadrage.
 */
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

  function modifie(column: string, change: Partial<Criterion>) {
    onChange(criteria.map((c) => (c.column === column ? { ...c, ...change } : c)));
  }

  return (
    <form
      className="panel filters"
      aria-label={t("storages.filters.title")}
      onSubmit={(event) => event.preventDefault()}
    >
      {offertes.map((offerte) => {
        const critere = criteria.find((c) => c.column === offerte.column);
        const offerts = operators(storage, offerte);
        return (
          <div key={offerte.column} className="field filter-column">
            <label htmlFor={`filtre-${offerte.column}`}>{offerte.label}</label>
            <div className="filter-controls">
              <select
                aria-label={t("storages.filters.operatorOn", { property: offerte.label })}
                value={critere?.operator ?? offerts[0]}
                onChange={(e) => modifie(offerte.column, { operator: e.target.value })}
              >
                {offerts.map((operateur) => (
                  <option key={operateur} value={operateur}>
                    {t(`storages.operators.${operateur}`)}
                  </option>
                ))}
              </select>
              <input
                id={`filtre-${offerte.column}`}
                value={critere?.value ?? ""}
                onChange={(e) => modifie(offerte.column, { value: e.target.value })}
              />
            </div>
          </div>
        );
      })}
    </form>
  );
}
