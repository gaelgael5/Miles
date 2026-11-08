import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useInstant } from "@miles/socle-web";

import { useIngestionCalls } from "../api/ingestion";
import { CallOutcome } from "./CallOutcome";

/**
 * Le journal des derniers appels d'UNE source : UNE ligne par appel, jamais par objet.
 *
 * Un dépôt de masse rendrait l'écran illisible autrement — le journal d'events prend n
 * lignes pour n objets écrits, celui-ci en prend une, avec son compte.
 *
 * La source est DONNÉE, et ne se choisit plus ici (Gael, 04/11/2026) : c'est le menu qui
 * la désigne, et un filtre de plus aurait permis de regarder le journal d'une source
 * depuis la page d'une autre.
 */
export function IngestionCalls({ source }: { source: string }) {
  const { t } = useTranslation();
  const instant = useInstant();
  const [page, setPage] = useState(1);
  // L'appel OUVERT, par son identifiant, et un seul à la fois : le détail se lit, il ne
  // se compare pas. Par l'identifiant et non par le rang, qui change de sens dès qu'on
  // tourne la page.
  const [ouvert, setOuvert] = useState<string | null>(null);
  const appels = useIngestionCalls(source, page);
  const pages = appels.data === undefined ? 1 : Math.max(1, Math.ceil(appels.data.total / appels.data.page_size));

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
              <li key={appel.id} className="row row-openable">
                <div className="row-main">
                  <button
                    type="button"
                    className="row-open row-title"
                    aria-expanded={ouvert === appel.id}
                    onClick={() => setOuvert(ouvert === appel.id ? null : appel.id)}
                  >
                    {instant(appel.received_at)}
                  </button>
                  <div className="row-sub">
                    <span className="mono">
                      {t(`ingestion.modes.${appel.mode}`, appel.mode)}
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
                {ouvert === appel.id && <CallOutcome ingestionId={appel.id} />}
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
