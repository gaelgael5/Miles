import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, useLogin } from "../api/auth";
import { startLoginUrl, usePublicConnectors } from "../api/oidc";

const OIDC_ERRORS = new Set([
  "connecteur_inconnu",
  "fournisseur_injoignable",
  "refus_fournisseur",
  "jeton_invalide",
  "state_invalide",
  "url_publique_absente",
  "configuration_connecteur",
]);

/** Erreur rendue par le retour OIDC : un code connu, jamais du texte libre de l'URL. */
function oidcErrorFromUrl(): { code: string; connector: string | null } | null {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("login_error");
  if (code === null) {
    return null;
  }
  return { code: OIDC_ERRORS.has(code) ? code : "unexpected", connector: params.get("connector") };
}

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
  const connectors = usePublicConnectors();
  const oidcError = oidcErrorFromUrl();
  const failedLabel = connectors.data?.find((c) => c.id === oidcError?.connector)?.label;

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
      {oidcError && (
        <p role="alert">
          {t(`login.oidcErrors.${oidcError.code}`, {
            connector: failedLabel ?? oidcError.connector ?? "",
          })}
        </p>
      )}
      {/* Sans connecteur actif, la connexion locale reste seule : l'OIDC ne ferme rien. */}
      {connectors.isSuccess && connectors.data.length > 0 && (
        <nav aria-label={t("login.oidcTitle")}>
          <p>{t("login.oidcTitle")}</p>
          {connectors.data.map((connector) => (
            <a key={connector.id} href={startLoginUrl(connector.id)}>
              {connector.label}
            </a>
          ))}
        </nav>
      )}
    </form>
  );
}
