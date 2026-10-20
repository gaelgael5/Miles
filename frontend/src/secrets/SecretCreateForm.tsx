import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, invalidField } from "../api/http";
import { type SecretSummary, slugFromLabel, useCreateSecret } from "../api/secrets";

interface SecretCreateFormProps {
  /** Type imposé par le champ qui appelle (sélecteur) ; sinon saisi. */
  secretType?: string;
  onCreated: (secret: SecretSummary) => void;
  onCancel?: () => void;
}

function errorKey(error: unknown): string {
  const field = invalidField(error);
  if (field !== null) {
    return `secrets.errors.invalid.${field}`;
  }
  if (error instanceof ApiError && error.status === 409) {
    return "secrets.errors.slugTaken";
  }
  return "secrets.errors.unexpected";
}

/** Création d'un secret, partagée par l'écran « Secrets » et la création à la volée du sélecteur. */
export function SecretCreateForm({ secretType, onCreated, onCancel }: SecretCreateFormProps) {
  const { t } = useTranslation();
  const create = useCreateSecret();
  const [label, setLabel] = useState("");
  // null tant que l'utilisateur n'a pas touché au slug : il suit alors le libellé.
  const [editedSlug, setEditedSlug] = useState<string | null>(null);
  const [typedType, setTypedType] = useState("");
  const [value, setValue] = useState("");
  const slug = editedSlug ?? slugFromLabel(label);

  function submit(event: FormEvent) {
    // Pas de remontée : ouvert par le sélecteur, ce formulaire est rendu dans un portail, et
    // React y fait remonter les événements jusqu'au formulaire de l'écran appelant.
    event.preventDefault();
    event.stopPropagation();
    const input = { slug, label, secret_type: secretType ?? typedType, value };
    create.mutate(input, {
      onSuccess: (secret) => {
        // La valeur ne reste pas dans l'état de l'écran une fois enregistrée.
        setValue("");
        onCreated(secret);
      },
    });
  }

  return (
    <form onSubmit={submit} aria-label={t("secrets.create.title")}>
      <label>
        {t("secrets.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label>
        {t("secrets.fields.slug")}
        <input required value={slug} onChange={(e) => setEditedSlug(e.target.value)} />
      </label>
      {secretType === undefined ? (
        <label>
          {t("secrets.fields.type")}
          <input
            required
            value={typedType}
            placeholder="GIT_TOKEN"
            onChange={(e) => setTypedType(e.target.value.toUpperCase())}
          />
        </label>
      ) : (
        <p>{t("secrets.create.fixedType", { type: secretType })}</p>
      )}
      <label>
        {t("secrets.fields.value")}
        <input
          type="password"
          required
          autoComplete="new-password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </label>
      <p>{t("secrets.create.neverShownAgain")}</p>
      {create.isError && <p role="alert">{t(errorKey(create.error))}</p>}
      <button type="submit" disabled={create.isPending}>
        {t("secrets.create.submit")}
      </button>
      {onCancel && (
        <button type="button" onClick={onCancel}>
          {t("secrets.cancel")}
        </button>
      )}
    </form>
  );
}
