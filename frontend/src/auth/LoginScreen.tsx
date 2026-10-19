import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, useLogin } from "../api/auth";

function errorKey(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) {
    return "login.errors.invalid";
  }
  if (error instanceof ApiError && error.status === 429) {
    return "login.errors.throttled";
  }
  return "login.errors.unexpected";
}

export function LoginScreen() {
  const { t } = useTranslation();
  const login = useLogin();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    login.mutate({ username, password });
  }

  return (
    <form onSubmit={submit} aria-labelledby="login-title">
      <h2 id="login-title">{t("login.title")}</h2>
      <label>
        {t("login.username")}
        <input
          required
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
      </label>
      <label>
        {t("login.password")}
        <input
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {login.isError && <p role="alert">{t(errorKey(login.error))}</p>}
      <button type="submit" disabled={login.isPending}>
        {t("login.submit")}
      </button>
    </form>
  );
}
