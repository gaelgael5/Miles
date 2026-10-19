import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, useBootstrap } from "../api/auth";

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
      <h2 id="bootstrap-title">{t("bootstrap.title")}</h2>
      <p>{t("bootstrap.intro")}</p>
      <label>
        {t("bootstrap.email")}
        <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label>
        {t("bootstrap.username")}
        <input required value={username} onChange={(e) => setUsername(e.target.value)} />
      </label>
      <label>
        {t("bootstrap.password")}
        <input
          type="password"
          required
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      <label>
        {t("bootstrap.confirmation")}
        <input
          type="password"
          required
          autoComplete="new-password"
          value={confirmation}
          onChange={(e) => setConfirmation(e.target.value)}
        />
      </label>
      {mismatch && <p role="alert">{t("bootstrap.errors.mismatch")}</p>}
      {failure && <p role="alert">{t(failure.key, failure.values)}</p>}
      <p>{t("bootstrap.warning")}</p>
      <button type="submit" disabled={mismatch || bootstrap.isPending}>
        {t("bootstrap.submit")}
      </button>
    </form>
  );
}
