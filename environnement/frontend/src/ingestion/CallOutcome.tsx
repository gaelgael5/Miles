import { useTranslation } from "react-i18next";

import { useCallOutcome } from "../api/ingestion";

/**
 * Ce qu'un dépôt est DEVENU, sous la ligne qu'on vient d'ouvrir.
 *
 * Demandé par Gael le 08/11/2026, après un import de 194 361 items dont 25 586 rejets :
 * le journal disait « traité » et rien d'autre, et le compte-rendu n'était exposé par
 * aucune route. Ce qu'il faut pour corriger un modèle, ce n'est pas la liste des objets
 * rejetés — elle est plafonnée à deux cents — c'est la synthèse par MOTIF, qui tient en
 * deux lignes quel que soit le nombre de rejets.
 */
export function CallOutcome({ ingestionId }: { ingestionId: string }) {
  const { t, i18n } = useTranslation();
  const issue = useCallOutcome(ingestionId);
  // La culture de l'interface décide du séparateur de milliers : vingt-cinq mille rejets
  // se lisent mal sans lui, et `toLocaleString` est proscrit dans ce dépôt.
  const nombre = new Intl.NumberFormat(i18n.language);

  if (issue.isPending) {
    return (
      <p className="muted" role="status">
        {t("ingestion.outcome.loading")}
      </p>
    );
  }
  if (issue.isError) {
    // Distinct d'« aucun rejet » : les confondre ferait conclure que tout est passé.
    return (
      <p className="alert" role="alert">
        {t("ingestion.outcome.unreadable")}
      </p>
    );
  }
  const { written, unchanged, rejected, items_read, failure_code, reasons, anomalies } = issue.data;
  return (
    <div className="call-outcome">
      {written !== null && (
        <p className="caption">
          {t("ingestion.outcome.counts", {
            written: nombre.format(written),
            unchanged: nombre.format(unchanged ?? 0),
            rejected: nombre.format(rejected ?? 0),
          })}
        </p>
      )}
      {items_read !== null && (
        <p className="help">
          {t("ingestion.outcome.itemsRead", { count: items_read, read: nombre.format(items_read) })}
        </p>
      )}
      {failure_code !== null && (
        <p className="alert" role="status">
          {t("ingestion.outcome.failure", {
            code: failure_code,
            detail: issue.data.failure_detail ?? "",
          })}
        </p>
      )}
      {reasons.length === 0 ? (
        <p className="help">{t("ingestion.outcome.noRejection")}</p>
      ) : (
        <>
          <p className="caption">{t("ingestion.outcome.reasons")}</p>
          <ul className="plain-list">
            {reasons.map((motif) => (
              <li key={`${motif.reason}|${motif.detail ?? ""}`} className="row row-compact">
                <div className="row-main">
                  <span className="mono">{motif.detail ?? motif.reason}</span>
                  <div className="row-sub">
                    {t(`ingestion.rejects.${motif.reason}`, motif.reason)}
                    {motif.sample_key !== null && (
                      <> {t("ingestion.outcome.sample", { key: motif.sample_key })}</>
                    )}
                  </div>
                </div>
                <span className="row-code">{nombre.format(motif.count)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {anomalies.map((anomalie) => (
        <p key={anomalie} className="help mono">
          {anomalie}
        </p>
      ))}
    </div>
  );
}
