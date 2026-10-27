import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "../layout/ConfirmDialog";
import { CopyButton } from "../layout/CopyButton";
import { PageHead } from "../layout/PageHead";
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
  const [confirmingDelete, setConfirmingDelete] = useState(false);
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
    <li className="row">
      <div className="row-main">
        <div className="row-title">{secret.label}</div>
        <div className="row-sub">{secret.slug}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("secrets.list.captionType")}</div>
        <div className="value">
          <span className="badge">{secret.secret_type}</span>
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("secrets.list.captionUsage")}</div>
        <div className="value">{t("secrets.list.usedBy", { count: secret.consumers.length })}</div>
      </div>
      <div className="actions row-actions">
      {/* « Copier » copie le slug, jamais la valeur : le navigateur ne l'a d'ailleurs pas. */}
      <CopyButton text={secret.slug} label={t("secrets.list.copySlug")} />
      <button type="button" className="btn btn-secondary" onClick={() => open("relabel")}>
        {t("secrets.list.relabel")}
      </button>
      <button type="button" className="btn btn-secondary" onClick={() => open("replace")}>
        {t("secrets.list.replaceValue")}
      </button>
      <button type="button" className="btn btn-danger" onClick={() => setConfirmingDelete(true)}>
        {t("secrets.list.delete")}
      </button>
      </div>
      {/* La suppression détruit la valeur chiffrée sans retour possible : un clic isolé
          ne doit pas suffire, d'où une validation explicite. */}
      {confirmingDelete && (
        <ConfirmDialog
          title={t("secrets.deleteConfirm.title")}
          confirmLabel={t("secrets.deleteConfirm.confirm")}
          cancelLabel={t("secrets.cancel")}
          onCancel={() => setConfirmingDelete(false)}
          onConfirm={() => {
            setConfirmingDelete(false);
            remove.mutate(secret.slug);
          }}
        >
          <p>{t("secrets.deleteConfirm.body", { label: secret.label, slug: secret.slug })}</p>
          {secret.consumers.length > 0 && (
            <p className="alert">
              {t("secrets.deleteConfirm.inUse", { count: secret.consumers.length })}
            </p>
          )}
        </ConfirmDialog>
      )}
      {mode !== "idle" && (
        <form className="row-detail" onSubmit={submit} aria-label={t(`secrets.list.${mode}`)}>
          <label className="field">
            {t(mode === "relabel" ? "secrets.fields.label" : "secrets.fields.newValue")}
            <input
              required
              type={mode === "replace" ? "password" : "text"}
              autoComplete={mode === "replace" ? "new-password" : "off"}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
          </label>
          <button type="submit" className="btn btn-primary">{t("secrets.save")}</button>
          <button type="button" className="btn btn-secondary" onClick={() => open("idle")}>
            {t("secrets.cancel")}
          </button>
        </form>
      )}
      {failed && <p className="alert" role="alert">{t(mutationErrorKey(failed))}</p>}
      {blockers !== null && (
        <div className="alert" role="alert">
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
        <p className="alert" role="alert">{t("secrets.errors.unexpected")}</p>
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
      <PageHead
        id="secrets-title"
        title={t("secrets.title")}
        lead={t("secrets.intro")}
        action={
          !creating && (
            <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
              {t("secrets.create.open")}
            </button>
          )
        }
      />
      {creating && (
        <SecretCreateForm onCreated={() => setCreating(false)} onCancel={() => setCreating(false)} />
      )}
      {secrets.isPending && <p className="muted" role="status">{t("secrets.list.loading")}</p>}
      {secrets.isError && <p className="alert" role="alert">{t("secrets.errors.unreachable")}</p>}
      {secrets.isSuccess && secrets.data.length === 0 && <p>{t("secrets.list.empty")}</p>}
      {secrets.isSuccess && secrets.data.length > 0 && (
        <ul className="card-list plain-list">
          {secrets.data.map((secret) => (
            <SecretRow key={secret.slug} secret={secret} />
          ))}
        </ul>
      )}
    </section>
  );
}
