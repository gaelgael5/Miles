import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useIngestionCalls } from "../api/ingestion";

/**
 * Le journal des derniers appels : UNE ligne par appel, jamais par objet.
 *
 * Un dépôt de masse rendrait l'écran illisible autrement — le journal d'events prend n
 * lignes pour n objets écrits, celui-ci en prend une, avec son compte.
 */
export function IngestionCalls() {
  const { t } = useTranslation();
  const [source, setSource] = useState("");
  const [page, setPage] = useState(1);
  const appels = useIngestionCalls(source, page);
  const pages = appels.data === undefined ? 1 : Math.max(1, Math.ceil(appels.data.total / appels.data.page_size));

  function filtre(valeur: string) {
    // Changer le filtre ramène à la première page : rester en page 4 d'une liste qui
    // n'en a plus que deux afficherait un vide qu'on prendrait pour un résultat.
    setSource(valeur);
    setPage(1);
  }

  if (appels.isError) {
    // Distinct de « aucun appel » : les confondre ferait conclure que tout va bien au
    // pire moment pour le conclure.
    return (
      <p className="alert" role="alert">
        {t("ingestion.calls.unreadable")}
      </p>
    );
  }
  return (
    <section className="card" aria-labelledby="ingestion-calls-title">
      <div className="card-head">
        <h2 id="ingestion-calls-title">{t("ingestion.calls.title")}</h2>
      </div>
      <form
        className="panel"
        aria-label={t("ingestion.calls.filter")}
        onSubmit={(event) => event.preventDefault()}
      >
        <label className="field">
          {t("ingestion.calls.source")}
          <select value={source} onChange={(event) => filtre(event.target.value)}>
            <option value="">{t("ingestion.calls.allSources")}</option>
            {(appels.data?.sources ?? []).map((nom) => (
              <option key={nom} value={nom}>
                {nom}
              </option>
            ))}
          </select>
        </label>
      </form>
      {appels.isPending ? (
        <p className="muted" role="status">
          {t("ingestion.calls.loading")}
        </p>
      ) : appels.data.calls.length === 0 ? (
        <p className="help">{t("ingestion.calls.none")}</p>
      ) : (
        <>
          <p className="caption">{t("ingestion.calls.found", { count: appels.data.total })}</p>
          <ul className="plain-list">
            {appels.data.calls.map((appel) => (
              <li key={appel.id} className="row">
                <div className="row-main">
                  <span className="row-title">
                    {new Date(appel.received_at).toLocaleString()}
                  </span>
                  <div className="row-sub">
                    <span className="mono">
                      {appel.source} · {t(`ingestion.modes.${appel.mode}`, appel.mode)}
                    </span>
                    {" · "}
                    {t("ingestion.calls.objects", { count: appel.object_count })}
                    {" · "}
                    {t("ingestion.calls.size", { bytes: appel.size_bytes })}
                  </div>
                </div>
                <p className="caption row-detail">
                  {/* Le libellé et le préfixe de la clé : jamais sa valeur. */}
                  {t("ingestion.calls.by", {
                    label: appel.key_label,
                    prefix: appel.key_prefix ?? t("ingestion.calls.unknownKey"),
                  })}
                  {" · "}
                  {t("ingestion.calls.version", { number: appel.version_number })}
                  {" · "}
                  {t(`ingestion.states.${appel.state}`, appel.state)}
                </p>
              </li>
            ))}
          </ul>
          <div className="actions">
            <button
              type="button"
              className="btn btn-secondary"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              {t("ingestion.calls.previous")}
            </button>
            <span className="caption">{t("ingestion.calls.page", { page, pages })}</span>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={page >= pages}
              onClick={() => setPage(page + 1)}
            >
              {t("ingestion.calls.next")}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
