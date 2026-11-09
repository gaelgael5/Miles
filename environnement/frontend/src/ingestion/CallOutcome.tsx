import { useTranslation } from "react-i18next";

import { useDuration } from "@miles/socle-web";

import { type CallOutcome as Issue, useCallOutcome } from "../api/ingestion";

/** L'écart entre deux instants, nul tant que l'un des deux n'a pas eu lieu. */
function ecart(debut: string | null, fin: string | null): number | null {
  if (debut === null || fin === null) {
    return null;
  }
  return new Date(fin).getTime() - new Date(debut).getTime();
}

/**
 * Les trois temps d'un import, et ils ne se confondent pas : l'attente en file ne dit
 * rien du coût du document, la lecture est le temps long, et l'écriture est celle qui
 * tient une transaction. Un seul nombre ferait chercher une lenteur au mauvais endroit.
 */
function Durations({ issue }: { issue: Issue }) {
  const { t } = useTranslation();
  const duree = useDuration();
  const attente = ecart(issue.received_at, issue.started_at);
  const total = ecart(issue.started_at, issue.finished_at);
  const lecture = ecart(issue.started_at, issue.apply_started_at);
  const ecriture = ecart(issue.apply_started_at, issue.finished_at);

  if (total === null) {
    return null;
  }
  return (
    <>
      <p className="caption">
        {t("ingestion.outcome.duration", { total: duree(total) })}
        {lecture !== null && ecriture !== null && (
          <>
            {" "}
            {t("ingestion.outcome.phases", {
              read: duree(lecture),
              write: duree(ecriture),
            })}
          </>
        )}
      </p>
      {attente !== null && attente >= 1000 && (
        <p className="help">{t("ingestion.outcome.queued", { wait: duree(attente) })}</p>
      )}
    </>
  );
}

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
  const removed = issue.data.items_removed;
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
      {removed !== null && removed > 0 && (
        // Montré seulement quand il y a eu des suppressions : « 0 supprimé » sur chaque
        // import ferait du nettoyage un bruit de fond, alors que c'est le geste qu'on
        // veut voir quand il a lieu. Le compte nul reste lisible dans le journal.
        <p className="help">
          {t("ingestion.outcome.itemsRemoved", {
            count: removed,
            removed: nombre.format(removed),
          })}
        </p>
      )}
      <Durations issue={issue.data} />
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
