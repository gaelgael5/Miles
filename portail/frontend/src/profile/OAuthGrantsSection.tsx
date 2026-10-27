import { useTranslation } from "react-i18next";

import { useOAuthGrants, useRevokeOAuthGrant } from "../api/oauth";

/** Ce que j'ai autorisé des clients OAuth à faire pour moi ; la révocation vaut aussitôt. */
export function OAuthGrantsSection() {
  const { t, i18n } = useTranslation();
  const grants = useOAuthGrants();
  const revoke = useRevokeOAuthGrant();
  const date = (value: string | null) =>
    value ? new Date(value).toLocaleString(i18n.language) : t("apiKeys.list.never");

  return (
    <section className="card" aria-labelledby="profile-oauth">
      <h2 id="profile-oauth">{t("oauth.grants.title")}</h2>
      {grants.isError && <p className="alert" role="alert">{t("oauth.errors.unexpected")}</p>}
      {grants.isSuccess && grants.data.length === 0 && <p className="muted">{t("oauth.grants.empty")}</p>}
      {revoke.isError && <p className="alert" role="alert">{t("oauth.errors.unexpected")}</p>}
      {grants.isSuccess && grants.data.length > 0 && (
        <ul className="card-list plain-list">
          {grants.data.map((g) => (
            <li key={g.id} className="row">
              <div className="row-main">
                <div className="row-title">{g.client}</div>
                <div className="row-sub">
                  {Object.entries(g.grants)
                    .map(([w, a]) => `${w} (${t(`apiKeys.access.${a}`)})`)
                    .join(", ") || t("apiKeys.list.noGrant")}
                </div>
              </div>
              <div className="cell">
                <div className="caption">{t("apiKeys.list.lastUsed")}</div>
                <div className="value">{date(g.last_used_at)}</div>
              </div>
              <div className="actions row-actions">
                <button type="button" className="btn btn-danger" disabled={revoke.isPending} onClick={() => revoke.mutate(g.id)}>
                  {t("oauth.grants.revoke")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
