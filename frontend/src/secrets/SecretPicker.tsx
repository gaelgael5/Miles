import { useId, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { useSecrets } from "../api/secrets";
import { SecretCreateForm } from "./SecretCreateForm";

interface SecretPickerProps {
  label: string;
  /** Le champ n'accepte que ce type : la liste est filtrée dessus. */
  secretType: string;
  /** Slug choisi, ou null. Le champ ne stocke jamais que le slug. */
  value: string | null;
  onChange: (slug: string | null) => void;
}

/**
 * Champ de type secret : une liste des secrets déclarés, avec création à la volée.
 *
 * Jamais un champ texte (standard globals « Secrets et coffres », §5 bis) : un champ
 * texte invite à coller la valeur au lieu de la référence, et une référence tapée à la
 * main ne se révèle fausse qu'à la première utilisation.
 */
export function SecretPicker({ label, secretType, value, onChange }: SecretPickerProps) {
  const { t } = useTranslation();
  const id = useId();
  const secrets = useSecrets(secretType);
  const [creating, setCreating] = useState(false);
  const known = secrets.data ?? [];
  // Signalée, pas vidée : effacer en silence une référence cassée dégraderait la
  // configuration sans que personne ne le voie.
  const orphan =
    value !== null && secrets.isSuccess && !known.some((secret) => secret.slug === value);

  return (
    <div>
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        value={value ?? ""}
        disabled={secrets.isPending}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
      >
        <option value="">{t("secrets.picker.none")}</option>
        {known.map((secret) => (
          <option key={secret.slug} value={secret.slug}>
            {secret.label}
          </option>
        ))}
        {orphan && <option value={value}>{t("secrets.picker.orphanOption", { slug: value })}</option>}
      </select>
      <button type="button" onClick={() => setCreating(true)}>
        {t("secrets.picker.createInline")}
      </button>
      {secrets.isError && <p role="alert">{t("secrets.errors.unreachable")}</p>}
      {orphan && <p role="alert">{t("secrets.picker.orphan", { slug: value })}</p>}
      {creating &&
        createPortal(
          <div role="dialog" aria-modal="true" aria-label={t("secrets.create.title")}>
            <SecretCreateForm
              secretType={secretType}
              onCreated={(secret) => {
                setCreating(false);
                onChange(secret.slug);
              }}
              onCancel={() => setCreating(false)}
            />
          </div>,
          document.body,
        )}
    </div>
  );
}
