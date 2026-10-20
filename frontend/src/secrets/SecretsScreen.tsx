import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, invalidField } from "../api/http";
import {
  type Consumer,
  type SecretSummary,
  useDeleteSecret,
  useRelabelSecret,
  useReplaceSecretValue,
  useSecrets,
} from "../api/secrets";
import { SecretCreateForm } from "./SecretCreateForm";

type Mode = "idle" | "relabel" | "replace";

function consumersOf(error: unknown): Consumer[] | null {
  if (error instanceof ApiError && error.status === 409) {
    const detail = error.detail as { consumers?: Consumer[] } | undefined;
    return detail?.consumers ?? null;
  }
  return null;
}

function mutationErrorKey(error: unknown): string {
  const field = invalidField(error);
  return field === null ? "secrets.errors.unexpected" : `secrets.errors.invalid.${field}`;
}

function SecretRow({ secret }: { secret: SecretSummary }) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>("idle");
  const [draft, setDraft] = useState("");
  const relabel = useRelabelSecret();
  const replace = useReplaceSecretValue();
  const remove = useDeleteSecret();
  const blockers = consumersOf(remove.error);
  const failed = relabel.error ?? replace.error;

  function open(next: Mode) {
    setDraft(next === "relabel" ? secret.label : "");
    setMode(next);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const done = { onSuccess: () => open("idle") };
    if (mode === "relabel") {
      relabel.mutate({ slug: secret.slug, label: draft }, done);
    } else {
      replace.mutate({ slug: secret.slug, value: draft }, done);
    }
  }

  return (
    <li>
      <strong>{secret.label}</strong> <code>{secret.slug}</code> {secret.secret_type}{" "}
      {t("secrets.list.usedBy", { count: secret.consumers.length })}
      {/* « Copier » copie le slug, jamais la valeur : le navigateur ne l'a d'ailleurs pas. */}
      <button type="button" onClick={() => void navigator.clipboard?.writeText(secret.slug)}>
        {t("secrets.list.copySlug")}
      </button>
      <button type="button" onClick={() => open("relabel")}>
        {t("secrets.list.relabel")}
      </button>
      <button type="button" onClick={() => open("replace")}>
        {t("secrets.list.replaceValue")}
      </button>
      <button type="button" onClick={() => remove.mutate(secret.slug)}>
        {t("secrets.list.delete")}
      </button>
      {mode !== "idle" && (
        <form onSubmit={submit} aria-label={t(`secrets.list.${mode}`)}>
          <label>
            {t(mode === "relabel" ? "secrets.fields.label" : "secrets.fields.newValue")}
            <input
              required
              type={mode === "replace" ? "password" : "text"}
              autoComplete={mode === "replace" ? "new-password" : "off"}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
          </label>
          <button type="submit">{t("secrets.save")}</button>
          <button type="button" onClick={() => open("idle")}>
            {t("secrets.cancel")}
          </button>
        </form>
      )}
      {failed && <p role="alert">{t(mutationErrorKey(failed))}</p>}
      {blockers !== null && (
        <div role="alert">
          <p>{t("secrets.errors.inUse")}</p>
          <ul>
            {blockers.map((c) => (
              <li key={`${c.kind}/${c.id}`}>
                {c.kind} {c.id}
              </li>
            ))}
          </ul>
        </div>
      )}
      {remove.isError && blockers === null && (
        <p role="alert">{t("secrets.errors.unexpected")}</p>
      )}
    </li>
  );
}

/** Secrets de l'instance : on les déclare ici, les autres écrans les sélectionnent. */
export function SecretsScreen() {
  const { t } = useTranslation();
  const secrets = useSecrets();
  const [creating, setCreating] = useState(false);

  return (
    <section aria-labelledby="secrets-title">
      <h2 id="secrets-title">{t("secrets.title")}</h2>
      <p>{t("secrets.intro")}</p>
      {creating ? (
        <SecretCreateForm onCreated={() => setCreating(false)} onCancel={() => setCreating(false)} />
      ) : (
        <button type="button" onClick={() => setCreating(true)}>
          {t("secrets.create.open")}
        </button>
      )}
      {secrets.isPending && <p role="status">{t("secrets.list.loading")}</p>}
      {secrets.isError && <p role="alert">{t("secrets.errors.unreachable")}</p>}
      {secrets.isSuccess && secrets.data.length === 0 && <p>{t("secrets.list.empty")}</p>}
      {secrets.isSuccess && secrets.data.length > 0 && (
        <ul>
          {secrets.data.map((secret) => (
            <SecretRow key={secret.slug} secret={secret} />
          ))}
        </ul>
      )}
    </section>
  );
}
