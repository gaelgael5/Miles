import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, ConfirmDialog } from "@miles/socle-web";
import {
  type GitIdentity,
  useGitIdentities,
  useRegisterGitIdentity,
  useRemoveGitIdentity,
} from "../api/gitIdentities";

function refusal(error: unknown): string {
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail !== null) {
    const detail = error.detail as { code?: string; reason?: string; field?: string };
    if (detail.code === "verification_impossible") {
      return `profile.git.errors.${detail.reason ?? "reponse_inattendue"}`;
    }
    if (detail.code === "forge_non_prise_en_charge") {
      return "profile.git.errors.forge";
    }
    if (detail.field === "token") {
      return "profile.git.errors.empty";
    }
  }
  return "profile.git.errors.unexpected";
}

/** Retirer son jeton est refusé pendant une prise de main (9def0adc, critère 12). */
function RemoveRefusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const detail =
    error instanceof ApiError && typeof error.detail === "object" && error.detail !== null
      ? (error.detail as { code?: string; workspace_id?: string; branch?: string })
      : null;
  return (
    <p className="alert" role="alert">
      {detail?.code === "prise_de_main_en_cours"
        ? t("profile.git.errors.holding", { workspace: detail.workspace_id, branch: detail.branch })
        : t("profile.git.errors.removal")}
    </p>
  );
}

function Connection({ identity }: { identity: GitIdentity }) {
  const { t } = useTranslation();
  const register = useRegisterGitIdentity(identity.connection_id);
  const remove = useRemoveGitIdentity(identity.connection_id);
  const [token, setToken] = useState("");
  const [confirming, setConfirming] = useState(false);
  const account = identity.account;

  function submit(event: FormEvent) {
    event.preventDefault();
    // Le champ est vidé quoi qu'il arrive : le jeton ne reste pas affiché dans la page.
    register.mutate(token, { onSettled: () => setToken("") });
  }

  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{identity.connection_label}</div>
        <div className="row-sub mono">{identity.base_url}</div>
      </div>
      <div className="row-detail">
        {account ? (
          <>
            <p>
              {t("profile.git.account", { login: account.login, name: account.name })}{" "}
              <span className="mono">{account.email}</span>{" "}
              {account.email_origin === "noreply" && (
                <span className="badge badge-warning">{t("profile.git.noreply")}</span>
              )}
            </p>
            <ul className="plain-list">
              {identity.repositories.map((r) => (
                <li key={r.workspace_id}>
                  {r.workspace_name} —{" "}
                  {t(`profile.git.write.${r.can_write === null ? "unknown" : String(r.can_write)}`)}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="muted">{t("profile.git.none")}</p>
        )}
        <form onSubmit={submit} aria-label={t("profile.git.form", { name: identity.connection_label })}>
          <label className="field">
            {t("profile.git.token")}
            <input
              type="password"
              autoComplete="off"
              required
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
          <p className="help">{t("profile.git.tokenHelp")}</p>
          {register.isError && (
            <p className="alert" role="alert">
              {t(refusal(register.error))}
            </p>
          )}
          {remove.isError && <RemoveRefusal error={remove.error} />}
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={register.isPending}>
              {t(account ? "profile.git.replace" : "profile.git.save")}
            </button>
            {account && (
              <button type="button" className="btn btn-secondary" onClick={() => setConfirming(true)}>
                {t("profile.git.remove")}
              </button>
            )}
          </div>
        </form>
      </div>
      {confirming && (
        <ConfirmDialog
          title={t("profile.git.removeTitle")}
          confirmLabel={t("profile.git.remove")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate();
          }}
        >
          {t("profile.git.removeBody", { name: identity.connection_label })}
        </ConfirmDialog>
      )}
    </li>
  );
}

/**
 * Identité git personnelle (story 033e5ff3) : sous ce jeton, la personne modifiera le
 * paramétrage en son nom. Il est vérifié par la forge et n'est jamais réaffiché.
 */
export function GitIdentitiesSection() {
  const { t } = useTranslation();
  const identities = useGitIdentities();
  return (
    <section className="card" aria-labelledby="profile-git">
      <h2 id="profile-git">{t("profile.git.title")}</h2>
      <p className="lead">{t("profile.git.intro")}</p>
      {identities.isSuccess && identities.data.length === 0 && (
        <p className="muted">{t("profile.git.noConnection")}</p>
      )}
      <ul className="card-list plain-list">
        {identities.data?.map((i) => (
          <Connection key={i.connection_id} identity={i} />
        ))}
      </ul>
    </section>
  );
}
