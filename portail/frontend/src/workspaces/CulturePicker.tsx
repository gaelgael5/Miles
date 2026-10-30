import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { type Culture, matchesFilter, useCultures } from "@miles/socle-web";

/**
 * Choisit une culture dans le CATALOGUE COMPLET, jamais dans les cultures actives de
 * l'application : traduire un paramétrage en thaï n'exige pas de lire le back-office en
 * thaï (story 639c25da, critère 9).
 *
 * Le filtre et la liste sont UN SEUL composant (Gael, 30/10/2026) : un champ de recherche
 * au-dessus d'une liste déroulante demandait de viser deux fois — taper, puis rouvrir la
 * liste pour choisir —, et ne montrait jamais combien d'entrées restaient. Ici, on tape et
 * on clique ce qu'on voit.
 *
 * La liste est BORNÉE : le catalogue compte plusieurs centaines de cultures, et toutes les
 * afficher ferait une page à faire défiler avant d'avoir filtré. Le compte restant est dit,
 * pour qu'un filtre trop large se voie au lieu de paraître vide.
 */
const MAX_SHOWN = 50;

export function CulturePicker({
  label,
  value,
  exclude = [],
  disabled = false,
  onChange,
}: {
  label: string;
  value: string;
  /** Déjà retenues : les proposer de nouveau ferait croire à un ajout qui ne se voit pas. */
  exclude?: readonly string[];
  disabled?: boolean;
  onChange: (code: string) => void;
}) {
  const { t } = useTranslation();
  const cultures = useCultures();
  const [filter, setFilter] = useState("");
  const listId = useId();
  const taken = new Set(exclude);
  const offered = (cultures.data ?? []).filter(
    (c) => !taken.has(c.code) && matchesFilter(c, filter),
  );
  const shown = offered.slice(0, MAX_SHOWN);

  return (
    <div className="culture-picker">
      <label className="field" htmlFor={listId}>
        {label}
        <input
          id={listId}
          type="search"
          autoComplete="off"
          disabled={disabled}
          placeholder={t("workspaceCultures.filterPlaceholder")}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </label>
      {cultures.isError && (
        <p className="alert" role="alert">
          {t("workspaceCultures.errors.catalogue")}
        </p>
      )}
      {cultures.isSuccess && offered.length === 0 && (
        <p className="muted" role="status">
          {t("workspaceCultures.noMatch", { filter })}
        </p>
      )}
      {shown.length > 0 && (
        <ul className="culture-list plain-list" aria-label={label}>
          {shown.map((culture) => (
            <li key={culture.code}>
              <button
                type="button"
                className="culture-option"
                disabled={disabled}
                // `aria-pressed` et non `aria-current` : c'est un choix qu'on bascule
                // dans une liste, pas la page où l'on se trouve.
                aria-pressed={culture.code === value}
                onClick={() => onChange(culture.code)}
              >
                {cultureLabel(culture)}
              </button>
            </li>
          ))}
        </ul>
      )}
      {offered.length > shown.length && (
        <p className="muted" role="status">
          {t("workspaceCultures.more", { count: offered.length - shown.length })}
        </p>
      )}
    </div>
  );
}

/** Le libellé natif d'abord : c'est celui que reconnaît qui parle la langue. */
export function cultureLabel(culture: Culture): string {
  return `${culture.code} — ${culture.label_native} (${culture.label_en})`;
}
