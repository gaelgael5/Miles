import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type Culture, matchesFilter, useCultures } from "@miles/socle-web";

/**
 * Choisit une culture dans le CATALOGUE COMPLET, jamais dans les cultures actives de
 * l'application : traduire un paramétrage en thaï n'exige pas de lire le back-office en
 * thaï (story 639c25da, critère 9). Le catalogue compte plusieurs centaines d'entrées,
 * d'où le filtre — même geste que l'écran des cultures de l'installation.
 */
export function CulturePicker({
  label,
  value,
  exclude = [],
  required = false,
  disabled = false,
  onChange,
}: {
  label: string;
  value: string;
  /** Déjà retenues : les proposer de nouveau ferait croire à un ajout qui ne se voit pas. */
  exclude?: readonly string[];
  required?: boolean;
  disabled?: boolean;
  onChange: (code: string) => void;
}) {
  const { t } = useTranslation();
  const cultures = useCultures();
  const [filter, setFilter] = useState("");
  const taken = new Set(exclude);
  const offered = (cultures.data ?? []).filter(
    (c) => !taken.has(c.code) && matchesFilter(c, filter),
  );

  return (
    <>
      <label className="field">
        {t("workspaceCultures.filter")}
        <input
          type="search"
          value={filter}
          disabled={disabled}
          onChange={(e) => setFilter(e.target.value)}
        />
      </label>
      <label className="field">
        {label}
        <select
          required={required}
          disabled={disabled}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">{t("workspaceCultures.choose")}</option>
          {offered.map((culture) => (
            <option key={culture.code} value={culture.code}>
              {cultureLabel(culture)}
            </option>
          ))}
        </select>
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
    </>
  );
}

/** Le libellé natif d'abord : c'est celui que reconnaît qui parle la langue. */
export function cultureLabel(culture: Culture): string {
  return `${culture.code} — ${culture.label_native} (${culture.label_en})`;
}
