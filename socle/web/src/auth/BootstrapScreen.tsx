import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { useBootstrap } from "../api/auth";
import { ApiError } from "../api/http";

function errorKey(error: unknown): { key: string; values?: Record<string, string> } {
  if (!(error instanceof ApiError)) {
    return { key: "bootstrap.errors.unexpected" };
  }
  if (error.status === 409) {
    return { key: "bootstrap.errors.closed" };
  }
  const detail = error.detail as { rule?: string; limit?: number; field?: string } | undefined;
  if (error.status === 422 && detail?.rule !== undefined) {
    return {
      key: `bootstrap.errors.weakPassword.${detail.rule}`,
      values: { limit: String(detail.limit) },
    };
  }
  if (error.status === 422 && detail?.field !== undefined) {
    return { key: `bootstrap.errors.invalid.${detail.field}` };
  }
  return { key: "bootstrap.errors.unexpected" };
}

export function BootstrapScreen() {
  const { t } = useTranslation();
  const bootstrap = useBootstrap();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const mismatch = confirmation !== "" && confirmation !== password;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirmation) {
      return;
    }
    bootstrap.mutate({ email, username, password });
  }

  const failure = bootstrap.isError ? errorKey(bootstrap.error) : null;
  return (
    <form onSubmit={submit} aria-labelledby="bootstrap-title">
      <h1 id="bootstrap-title">{t("bootstrap.title")}</h1>
      <p className="lead">{t("bootstrap.intro")}</p>
      <div className="card" style={{ marginTop: 24 }}>
      <label className="field">
        {t("bootstrap.email")}
        <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="field">
        {t("bootstrap.username")}
        <input required value={username} onChange={(e) => setUsername(e.target.value)} />
      </label>
      <label className="field">
        {t("bootstrap.password")}
        <input
          type="password"
          required
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      <label className="field">
        {t("bootstrap.confirmation")}
        <input
          type="password"
          required
          autoComplete="new-password"
          value={confirmation}
          onChange={(e) => setConfirmation(e.target.value)}
        />
      </label>
      {mismatch && <p className="alert" role="alert">{t("bootstrap.errors.mismatch")}</p>}
      {failure && <p className="alert" role="alert">{t(failure.key, failure.values)}</p>}
      <button
        type="submit"
        className="btn btn-primary btn-block"
        disabled={mismatch || bootstrap.isPending}
      >
        {t("bootstrap.submit")}
      </button>
      </div>
      {/* Avertissement de la maquette : ce chemin ne s'ouvre qu'une fois, et se journalise. */}
      <p className="alert">{t("bootstrap.warning")}</p>
    </form>
  );
}
