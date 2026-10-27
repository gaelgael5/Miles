import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { type ActorIdentity, useActorIdentity, useRemoveActorIdentity, useSetActorIdentity } from "../api/actorIdentity";
import { ApiError } from "../api/http";
import { CopyButton } from "../layout/CopyButton";

function errorKey(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "profile.actor.errors.taken";
  }
  if (error instanceof ApiError && error.status === 422) {
    return "profile.actor.errors.invalid";
  }
  return "profile.actor.errors.unexpected";
}

function Editor({ current }: { current: ActorIdentity }) {
  const { t } = useTranslation();
  const save = useSetActorIdentity();
  const remove = useRemoveActorIdentity();
  // Semé une fois depuis la valeur lue : l'éditeur est remonté (clé) quand elle change.
  const [draft, setDraft] = useState(current.actor ?? "");

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate(draft);
  }

  return (
    <form onSubmit={submit} aria-label={t("profile.actor.title")}>
      <label className="field">
        {t("profile.actor.field")}
        <input className="mono" value={draft} spellCheck={false} onChange={(e) => setDraft(e.target.value)} />
      </label>
      <p className="help">{t("profile.actor.help")}</p>
      {(save.isError || remove.isError) && (
        <p className="alert" role="alert">{t(errorKey(save.error ?? remove.error))}</p>
      )}
      {save.isSuccess && <p className="muted" role="status">{t("profile.actor.saved")}</p>}
      <div className="actions">
        <button type="button" className="btn btn-secondary" onClick={() => setDraft(crypto.randomUUID())}>
          {t("profile.actor.generate")}
        </button>
        <CopyButton text={draft} label={t("profile.actor.copy")} disabled={!draft} />
        <button type="submit" className="btn btn-primary" disabled={!draft.trim() || save.isPending}>
          {t("profile.actor.save")}
        </button>
        {current.actor !== null && (
          <button type="button" className="btn btn-danger" disabled={remove.isPending} onClick={() => remove.mutate(undefined, { onSuccess: () => setDraft("") })}>
            {t("profile.actor.remove")}
          </button>
        )}
      </div>
    </form>
  );
}

/** Identité d'acteur pour le portail : l'agent signe vos modifications « via » sa clé. */
export function ActorIdentitySection() {
  const { t } = useTranslation();
  const identity = useActorIdentity();
  return (
    <section className="card" aria-labelledby="profile-actor">
      <h2 id="profile-actor">{t("profile.actor.title")}</h2>
      {identity.isError && <p className="alert" role="alert">{t("profile.actor.errors.unexpected")}</p>}
      {identity.data && <Editor key={identity.data.actor ?? ""} current={identity.data} />}
    </section>
  );
}
