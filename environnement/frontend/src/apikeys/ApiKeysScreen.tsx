import { useTranslation } from "react-i18next";

import { useInstant } from "@miles/socle-web";

import { type ApiKey, useApiKeys, useDeclaredSources, useRevokeKey } from "../api/apikeys";
import { NewApiKey } from "./NewApiKey";

/**
 * La page des clés d'API d'ingestion de cet environnement (Gael, 02/11/2026).
 *
 * Réservée à l'administrateur, comme tout cet écran : une clé d'ingestion n'ouvre jamais
 * ces routes — elle ne sait que déposer.
 */
export function ApiKeysScreen() {
  const { t } = useTranslation();
  const keys = useApiKeys();
  const sources = useDeclaredSources();

  if (keys.isPending || sources.isPending) {
    return (
      <p className="muted" role="status">
        {t("apiKeys.loading")}
      </p>
    );
  }
  if (keys.isError || sources.isError) {
    return (
      <p className="alert" role="alert">
        {t("apiKeys.unreadable")}
      </p>
    );
  }
  return (
    <section aria-labelledby="api-keys-title">
      <div className="page-head">
        <h1 id="api-keys-title">{t("apiKeys.title")}</h1>
      </div>
      <p className="help">{t("apiKeys.intro")}</p>
      <NewApiKey sources={sources.data.sources} />
      {keys.data.length === 0 ? (
        <p className="help">{t("apiKeys.none")}</p>
      ) : (
        <ul className="plain-list">
          {keys.data.map((key) => (
            <ApiKeyRow key={key.id} apiKey={key} />
          ))}
        </ul>
      )}
    </section>
  );
}

function ApiKeyRow({ apiKey }: { apiKey: ApiKey }) {
  const { t } = useTranslation();
  const instant = useInstant();
  const revoke = useRevokeKey();

  return (
    <li className="row">
      <div className="row-main">
        <span className="row-title">{apiKey.label}</span>
        <div className="row-sub">
          <span className="mono">{apiKey.prefix}…</span>
          {" · "}
          <span className="mono">{apiKey.sources.join(" · ")}</span>
        </div>
      </div>
      <p className="caption row-detail">
        {t("apiKeys.createdBy", {
          who: apiKey.created_by,
          when: instant(apiKey.created_at),
        })}
        {" · "}
        {/* Jamais utilisée se distingue d'utilisée : c'est ce qui permet de révoquer sans
            risque, en sachant si quelqu'un s'en sert encore. */}
        {apiKey.last_used_at === null
          ? t("apiKeys.neverUsed")
          : t("apiKeys.lastUsed", { when: instant(apiKey.last_used_at) })}
      </p>
      {apiKey.missing_sources.length > 0 && (
        // L'octroi reste écrit : une version suivante peut ramener la source, et le
        // réécrire d'office effacerait à qui on avait ouvert quoi.
        <p className="alert row-detail" role="status">
          {t("apiKeys.missingSources", { sources: apiKey.missing_sources.join(" · ") })}
        </p>
      )}
      {apiKey.revoked_at !== null ? (
        // Une clé révoquée reste visible : l'effacer rendrait son histoire illisible.
        // Le test porte sur le CHAMP et non sur un booléen dérivé : lui seul restreint le
        // type, et `revoked_at ?? ""` affichait « Invalid Date » sur une clé active.
        <p className="muted row-detail">
          {t("apiKeys.revoked", { when: instant(apiKey.revoked_at) })}
        </p>
      ) : (
        <div className="actions row-detail">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={revoke.isPending}
            onClick={() => revoke.mutate(apiKey.id)}
          >
            {t("apiKeys.revoke")}
          </button>
        </div>
      )}
    </li>
  );
}
