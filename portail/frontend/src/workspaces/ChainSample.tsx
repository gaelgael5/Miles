import { useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * Échantillon source de test (Gael, 24/10/2026) : on l'enregistre une fois, puis il ne
 * reste qu'une ligne. La fenêtre ne sert qu'à le saisir ; l'écran de la chaîne n'a pas à
 * porter en permanence une zone de texte qu'on remplit une fois sur dix.
 *
 * Il vit en base, pas dans git : c'est un cas d'essai, pas du paramétrage. Revers dit
 * ici même, parce qu'on ne le devine pas : il ne suit ni publication ni retour arrière.
 */
/**
 * L'échantillon lu, ou `null` s'il n'est pas du JSON. Rendu dans une enveloppe pour
 * distinguer « illisible » (null) de « lisible et vaut null » — un échantillon vide est
 * légitime, la source vaut alors null (Gael, 22/10/2026).
 *
 * Partagé par l'écran de la chaîne et celui d'une étape : les deux doivent lire le même
 * échantillon de la même façon, sans quoi l'un exécute ce que l'autre refuse.
 */
export function parsedSample(text: string): { value: unknown } | null {
  if (!text.trim()) {
    return { value: null };
  }
  try {
    return { value: JSON.parse(text) };
  } catch {
    return null;
  }
}

export function ChainSample({
  sample,
  readOnly,
  pending,
  onSave,
}: {
  sample: string | null;
  readOnly: boolean;
  pending: boolean;
  onSave: (sample: string | null) => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [pasteFailed, setPasteFailed] = useState(false);

  function open() {
    setText(sample ?? "");
    setPasteFailed(false);
    setEditing(true);
  }

  async function paste() {
    try {
      setText(await navigator.clipboard.readText());
      setPasteFailed(false);
    } catch {
      // Le navigateur refuse la lecture du presse-papiers (permission, page non
      // sécurisée) : on le dit, la saisie à la main restant toujours possible.
      setPasteFailed(true);
    }
  }

  if (!editing) {
    return (
      <div className="row row-sample">
        <div className="row-main">
          <div className="row-title">{t("chains.sample.title")}</div>
          <div className="row-sub">
            {sample === null
              ? t("chains.sample.none")
              : t("chains.sample.saved", { size: sample.length })}
          </div>
        </div>
        {!readOnly && (
          <div className="actions row-actions">
            <button type="button" className="btn btn-secondary" onClick={open}>
              {sample === null ? t("chains.sample.add") : t("chains.sample.change")}
            </button>
            {sample !== null && (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={pending}
                onClick={() => onSave(null)}
              >
                {t("chains.sample.clear")}
              </button>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="overlay" onClick={() => setEditing(false)}>
      <div
        className="dialog dialog-wide"
        role="dialog"
        aria-modal="true"
        aria-label={t("chains.sample.title")}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setEditing(false);
          }
        }}
      >
        <div className="card">
          <h2>{t("chains.sample.title")}</h2>
          <p className="help">{t("chains.sample.explain")}</p>
          <div className="actions">
            <button type="button" className="btn btn-secondary" onClick={() => void paste()}>
              {t("chains.sample.paste")}
            </button>
          </div>
          {pasteFailed && (
            <p className="alert" role="alert">
              {t("chains.sample.pasteFailed")}
            </p>
          )}
          <label className="field">
            {t("chains.fields.sample")}
            <textarea
              rows={14}
              spellCheck={false}
              className="mono"
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          <div className="actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={pending}
              onClick={() => {
                setEditing(false);
                // Vider le champ vaut effacer : un échantillon vide n'est pas un cas.
                onSave(text.trim() === "" ? null : text);
              }}
            >
              {t("chains.sample.save")}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setEditing(false)}
            >
              {t("chains.sample.cancel")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
