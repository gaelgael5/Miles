import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { refusKey, slugFromLabel } from "../api/environments";

/**
 * Le couple libellé / slug, pour la création comme pour le renommage.
 *
 * Un seul composant parce qu'une seule règle gouverne les deux champs, et qu'elle est le
 * vrai contenu de cet écran : **le slug suit le libellé tant que personne n'y a touché.**
 * Dès qu'il est édité, le libellé cesse de le réécrire. Sans cela, corriger le libellé
 * après avoir choisi son slug efface le choix sans rien dire — la panne classique de ce
 * couple de champs, et elle ne se voit qu'à l'usage.
 */
export function EnvironmentForm({
  idPrefix = "environment",
  label: labelInitial,
  slug: slugInitial,
  submitLabel,
  pending,
  error,
  onSubmit,
  onCancel,
}: {
  /**
   * Préfixe des `id` des champs. Il existe parce que ce formulaire s'ouvre aussi en
   * raccourci depuis l'écran d'appariement, où plusieurs lignes peuvent l'afficher en
   * même temps : deux `id` identiques feraient pointer le libellé de l'un sur le champ
   * de l'autre, et la saisie paraîtrait ne pas répondre.
   */
  idPrefix?: string;
  label: string;
  slug: string;
  submitLabel: string;
  pending: boolean;
  error: unknown;
  onSubmit: (input: { label: string; slug: string }) => void;
  onCancel?: () => void;
}) {
  const { t } = useTranslation();
  const [label, setLabel] = useState(labelInitial);
  const [slug, setSlug] = useState(slugInitial);
  // Au renommage, le slug existe déjà : il a été choisi une fois, et renommer le libellé
  // ne doit pas le reprendre à son auteur.
  const [slugChoisi, setSlugChoisi] = useState(slugInitial !== "");

  function changeLabel(valeur: string) {
    setLabel(valeur);
    if (!slugChoisi) {
      setSlug(slugFromLabel(valeur));
    }
  }

  function soumettre(event: FormEvent) {
    event.preventDefault();
    onSubmit({ label, slug });
  }

  return (
    <form className="panel" onSubmit={soumettre}>
      <div className="field">
        <label htmlFor={`${idPrefix}-label`}>{t("environments.form.label")}</label>
        <input
          id={`${idPrefix}-label`}
          type="text"
          value={label}
          maxLength={80}
          autoComplete="off"
          onChange={(event) => changeLabel(event.target.value)}
        />
        <p className="help">{t("environments.form.labelHelp")}</p>
      </div>
      <div className="field">
        <label htmlFor={`${idPrefix}-slug`}>{t("environments.form.slug")}</label>
        <input
          id={`${idPrefix}-slug`}
          type="text"
          value={slug}
          maxLength={48}
          autoComplete="off"
          onChange={(event) => {
            setSlugChoisi(true);
            setSlug(event.target.value);
          }}
        />
        <p className="help">{t("environments.form.slugHelp")}</p>
      </div>
      {error !== null && error !== undefined && (
        <p className="alert alert-danger" role="alert">
          {t(refusKey(error))}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={pending}>
          {submitLabel}
        </button>
        {onCancel !== undefined && (
          <button type="button" className="btn btn-secondary" onClick={onCancel}>
            {t("environments.form.cancel")}
          </button>
        )}
      </div>
    </form>
  );
}
