import { useTranslation } from "react-i18next";

import { marksIn } from "../api/tradsKeys";

/**
 * Un champ de valeur, dans SA langue (story 289c8d9f, critères 7 à 11).
 *
 * `lang` et `dir` sont portés par le CHAMP, pas par la page : un champ sans langue
 * déclarée hérite de celle de la page, et un traducteur arabe se retrouve avec le
 * correcteur orthographique français, les suggestions de saisie françaises et des règles
 * de coupure de ligne fausses.
 *
 * `dir` vient de la CULTURE, jamais du contenu. La facilité consiste à laisser le
 * navigateur deviner d'après le premier caractère fort (`dir="auto"`) : une traduction
 * arabe qui commence par un nom de marque latin ou par un chiffre serait alors disposée
 * de gauche à droite, et l'erreur n'apparaîtrait que sur certaines valeurs — donc tard.
 */
export function ValueField({
  culture,
  direction,
  value,
  required,
  readOnly,
  onChange,
}: {
  culture: string;
  direction: "ltr" | "rtl";
  value: string;
  required?: boolean;
  readOnly?: boolean;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const marks = marksIn(value);
  return (
    <label className="field">
      <span className="value-head">
        <code>{culture}</code>
        {direction === "rtl" && (
          <span className="rtl-tag"> {t("tradsKeys.rightToLeft")}</span>
        )}
        {required && <span className="rtl-tag"> {t("tradsKeys.requiredTag")}</span>}
      </span>
      <textarea
        className="value-field"
        // Déclarés sur le champ, et le navigateur en tire le dictionnaire du correcteur.
        lang={culture}
        dir={direction}
        rows={1}
        required={required}
        readOnly={readOnly}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      {marks.length > 0 && (
        <span className="marks">{t("tradsKeys.marks", { marks: marks.join(", ") })}</span>
      )}
    </label>
  );
}

/**
 * Une valeur affichée en lecture, dans sa langue. Même règles que le champ : le sens vient
 * de la culture, et chaque cellule est isolée de ses voisines pour que la ponctuation de
 * bord de chacune reste à sa place.
 */
export function ValueCell({
  culture,
  direction,
  value,
}: {
  culture: string;
  direction: "ltr" | "rtl";
  value: string | undefined;
}) {
  const { t } = useTranslation();
  if (value === undefined) {
    // Une traduction manquante est un état NORMAL d'une clé qu'on vient d'ajouter :
    // l'écran la compte et la retrouve, il ne crie pas.
    return <span className="muted">{t("tradsKeys.untranslated")}</span>;
  }
  return (
    <span className="value-cell" lang={culture} dir={direction}>
      {value}
    </span>
  );
}
