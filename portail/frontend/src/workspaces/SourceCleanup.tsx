import { useTranslation } from "react-i18next";

/**
 * La règle de nettoyage d'une entrée de source (Gael, 09/11/2026) : « suppression des
 * items plus dans l'import depuis N jours ».
 *
 * Réservée au mode fichier, et l'appelant ne la monte que là : « absent de l'import » n'a
 * de sens que pour un dépôt qui prétend porter l'image complète du référentiel. Un dépôt
 * unitaire ou par tableau ne dit rien de ce qu'il ne contient pas.
 *
 * Le délai n'est pas un réglage de confort : c'est lui qui protège d'un export tronqué.
 * L'item absent est marqué, un import complet suivant lève la marque, et rien n'a été
 * supprimé entre-temps.
 */
export function SourceCleanup({
  days,
  rank,
  disabled,
  defaultDays,
  onChange,
}: {
  days: number | null;
  rank: number;
  disabled: boolean;
  defaultDays: number;
  onChange: (days: number | null) => void;
}) {
  const { t } = useTranslation();

  return (
    <>
      <label className="field-check">
        <input
          type="checkbox"
          disabled={disabled}
          checked={days !== null}
          onChange={(e) => onChange(e.target.checked ? defaultDays : null)}
        />
        {t("sources.fields.removeMissing")}
      </label>
      {days !== null && (
        <>
          <label className="field">
            {t("sources.fields.missingDays", { rank: rank + 1 })}
            <input
              required
              type="number"
              min={1}
              step={1}
              disabled={disabled}
              value={days}
              // Effacé : on retombe sur le défaut plutôt que sur NaN, et jamais sur zéro —
              // zéro supprimerait à l'import suivant ce que celui-ci vient de marquer.
              onChange={(e) => onChange(Number(e.target.value) || defaultDays)}
            />
          </label>
          <p className="help">{t("sources.form.missingDaysHelp", { count: days })}</p>
        </>
      )}
    </>
  );
}
