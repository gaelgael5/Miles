import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/http";
import { type Access, type ConsentView, useConsentView, useDecide } from "../api/oauth";
import { forgetPendingAuthorize, navigation } from "./pendingAuthorize";

/** Les paramètres OAuth de l'adresse, tels que claude.ai les a envoyés. */
function authorizeParams(): Record<string, string> {
  return Object.fromEntries(new URLSearchParams(window.location.search).entries());
}

function leave(url: string) {
  forgetPendingAuthorize();
  navigation.assign(url);
}

function refusalKey(error: unknown): string {
  if (error instanceof ApiError && typeof error.detail === "string") {
    return `oauth.consent.refused.${error.detail}`;
  }
  return "oauth.consent.refused.unexpected";
}

function Choices({ view, params }: { view: ConsentView; params: Record<string, string> }) {
  const { t } = useTranslation();
  const decide = useDecide();
  // Rien de coché d'avance : la personne choisit ce qu'elle délègue, workspace par workspace.
  const [chosen, setChosen] = useState<Record<string, Access | "">>({});
  const grants = Object.entries(chosen)
    .filter((entry): entry is [string, Access] => entry[1] !== "")
    .map(([workspace_id, access]) => ({ workspace_id, access }));

  function send(decision: "approve" | "deny") {
    decide.mutate({ params, decision, grants }, { onSuccess: (done) => leave(done.redirect) });
  }

  return (
    <>
      {view.allowed.length === 0 ? (
        <p className="alert" role="alert">{t("oauth.consent.noRights")}</p>
      ) : (
        <fieldset className="field">
          <legend>{t("oauth.consent.grants")}</legend>
          {view.allowed.map((w) => (
            <label key={w.workspace_id} className="field">
              {w.name} <span className="mono muted">{w.workspace_id}</span>
              <select
                value={chosen[w.workspace_id] ?? ""}
                onChange={(e) => setChosen({ ...chosen, [w.workspace_id]: e.target.value as Access | "" })}
              >
                <option value="">{t("apiKeys.access.none")}</option>
                <option value="lecture">{t("apiKeys.access.lecture")}</option>
                {w.access === "ecriture" && <option value="ecriture">{t("apiKeys.access.ecriture")}</option>}
              </select>
            </label>
          ))}
        </fieldset>
      )}
      {decide.isError && <p className="alert" role="alert">{t(refusalKey(decide.error))}</p>}
      <div className="actions">
        {view.allowed.length > 0 && (
          <button type="button" className="btn btn-primary" disabled={decide.isPending || grants.length === 0} onClick={() => send("approve")}>
            {t("oauth.consent.approve")}
          </button>
        )}
        <button type="button" className="btn btn-secondary" disabled={decide.isPending} onClick={() => send("deny")}>
          {t("oauth.consent.deny")}
        </button>
      </div>
    </>
  );
}

/** Consentement OAuth (story 9f09cd8b) : ce qu'un client comme claude.ai pourra faire pour vous. */
export function ConsentScreen() {
  const { t } = useTranslation();
  const [params] = useState(authorizeParams);
  const view = useConsentView(params);
  const data = view.data;

  if (data && "redirect" in data) {
    // Demande mal formée mais adresse de retour sûre : le client reçoit le refus normalisé.
    leave(data.redirect);
    return null;
  }
  return (
    <section className="narrow" aria-labelledby="consent-title">
      <div className="card">
        <h1 id="consent-title">{t("oauth.consent.title")}</h1>
        {view.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
        {view.isError && <p className="alert" role="alert">{t(refusalKey(view.error))}</p>}
        {data && (
          <>
            <p className="lead">{t("oauth.consent.intro", { client: data.client.label })}</p>
            <p className="help">{t("oauth.consent.returnTo", { host: new URL(data.redirect_uri).host })}</p>
            <Choices view={data} params={params} />
          </>
        )}
      </div>
    </section>
  );
}
