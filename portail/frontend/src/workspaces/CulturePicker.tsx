import { type KeyboardEvent, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { type Culture, matchesFilter, useCultures } from "@miles/socle-web";

/**
 * Choisit une culture dans le CATALOGUE COMPLET, jamais dans les cultures actives de
 * l'application : traduire un paramétrage en thaï n'exige pas de lire le back-office en
 * thaï (story 639c25da, critère 9).
 *
 * UN SEUL champ (Gael, 30/10/2026) : on écrit, la liste se déplie et se filtre ; on
 * clique, elle se replie et le champ porte le choix. Les formes précédentes — un filtre
 * au-dessus d'une liste déroulante, puis un filtre au-dessus d'une liste toujours
 * ouverte — demandaient de viser deux fois et occupaient la place d'une demi-page.
 *
 * Le clavier fait tout ce que la souris fait : flèches pour parcourir, Entrée pour
 * choisir, Échap pour refermer. Sans lui, un champ de saisie n'est utilisable que par
 * ceux qui voient et visent, et le catalogue compte plusieurs centaines d'entrées.
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
  // `null` : aucune saisie en cours, le champ montre le choix courant. On ne recopie
  // donc jamais `value` dans un état — le vider de l'extérieur vide le champ tout seul.
  const [typed, setTyped] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputId = useId();
  const listId = useId();
  const blurTimer = useRef<number | undefined>(undefined);

  const taken = new Set(exclude);
  const chosen = (cultures.data ?? []).find((c) => c.code === value);
  const shownText = typed ?? (chosen ? cultureLabel(chosen) : "");
  // Filtré sur ce qui est TAPÉ seulement : sans cela, le libellé du choix courant
  // servirait de filtre et la liste ne montrerait plus que lui.
  const offered = (cultures.data ?? []).filter(
    (c) => !taken.has(c.code) && matchesFilter(c, typed ?? ""),
  );
  const shown = offered.slice(0, MAX_SHOWN);
  const current = shown[Math.min(active, shown.length - 1)];

  function choose(culture: Culture) {
    onChange(culture.code);
    setTyped(null);
    setOpen(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActive((i) => {
        const next = event.key === "ArrowDown" ? i + 1 : i - 1;
        return Math.max(0, Math.min(next, shown.length - 1));
      });
      return;
    }
    if (event.key === "Enter" && open && current) {
      // Sans cela, Entrée soumettrait le formulaire avec le champ à moitié tapé.
      event.preventDefault();
      choose(current);
    }
  }

  return (
    <div className="culture-picker">
      <label className="field" htmlFor={inputId}>
        {label}
        <input
          id={inputId}
          type="text"
          role="combobox"
          autoComplete="off"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && current ? `${listId}-${current.code}` : undefined}
          disabled={disabled}
          placeholder={t("workspaceCultures.filterPlaceholder")}
          value={shownText}
          onChange={(e) => {
            setTyped(e.target.value);
            setOpen(true);
            setActive(0);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          onBlur={() => {
            // Différé : un clic sur une option déclenche le blur AVANT le clic, et
            // refermer tout de suite retirerait l'option sous le curseur.
            blurTimer.current = window.setTimeout(() => setOpen(false), 120);
          }}
        />
      </label>
      {cultures.isError && (
        <p className="alert" role="alert">
          {t("workspaceCultures.errors.catalogue")}
        </p>
      )}
      {open && (
        <ul className="culture-list plain-list" role="listbox" id={listId} aria-label={label}>
          {shown.map((culture, index) => (
            <li
              key={culture.code}
              id={`${listId}-${culture.code}`}
              role="option"
              aria-selected={culture.code === value}
              className={index === Math.min(active, shown.length - 1) ? "culture-option active" : "culture-option"}
              // `mousedown` et non `click` : il précède le blur du champ, et c'est ce qui
              // rend le choix possible sans courir après la fermeture.
              onMouseDown={(e) => {
                e.preventDefault();
                window.clearTimeout(blurTimer.current);
                choose(culture);
              }}
              onMouseEnter={() => setActive(index)}
            >
              {cultureLabel(culture)}
            </li>
          ))}
          {shown.length === 0 && (
            <li className="culture-empty" role="presentation">
              {t("workspaceCultures.noMatch", { filter: typed ?? "" })}
            </li>
          )}
          {offered.length > shown.length && (
            <li className="culture-empty" role="presentation">
              {t("workspaceCultures.more", { count: offered.length - shown.length })}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

/** Le libellé natif d'abord : c'est celui que reconnaît qui parle la langue. */
export function cultureLabel(culture: Culture): string {
  return `${culture.code} — ${culture.label_native} (${culture.label_en})`;
}
