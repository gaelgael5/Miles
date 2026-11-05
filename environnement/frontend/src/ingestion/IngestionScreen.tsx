import { useTranslation } from "react-i18next";

import { useInstant } from "@miles/socle-web";

import { type Health, useIngestionHealth } from "../api/ingestion";

/**
 * L'écran du service d'ingestion : son état de santé (Gael, 02/11/2026).
 *
 * « L'état de santé », interrogé, c'était « les deux » : le point d'entrée répond, et
 * les dépôts de masse avancent. **La seconde moitié n'a rien à mesurer**, et cet écran
 * le dit — le mode fichier n'est pas encore servi, donc il n'existe aucune file. Un
 * compteur à zéro laisserait croire qu'on surveille quelque chose.
 *
 * Les méthodes et le journal n'y sont plus (Gael, 04/11/2026) : ils appartiennent à une
 * SOURCE, qui a sa page sous ce service dans le menu. Ce qui reste ici est ce qui vaut
 * pour toutes — la version servie, les clés, les dépôts — et c'est ce qu'on vient
 * regarder quand on ne sait pas encore quelle source est en cause.
 */
export function IngestionScreen() {
  const { t } = useTranslation();
  const health = useIngestionHealth();

  // Le titre de la page ne dépend pas de ses données (Gael, 05/11/2026) : rendus À LA
  // PLACE de la page, la lecture et le refus laissaient une phrase seule dans un coin,
  // sans dire de quelle page ils parlaient.
  return (
    <section aria-labelledby="ingestion-title">
      <div className="page-head">
        <h1 id="ingestion-title">{t("ingestion.title")}</h1>
      </div>
      {health.isPending && (
        <p className="muted" role="status">
          {t("ingestion.loading")}
        </p>
      )}
      {health.isError && (
        <p className="alert" role="alert">
          {t("ingestion.unreadable")}
        </p>
      )}
      {health.data !== undefined && <ServiceHealth health={health.data} />}
    </section>
  );
}

function ServiceHealth({ health }: { health: Health }) {
  const { t } = useTranslation();
  const instant = useInstant();

  if (health.version_number === null) {
    // L'état normal d'une stack neuve, et non une panne : sans version servie, aucune
    // source n'est déclarée, donc aucun point d'entrée n'existe.
    return <p className="help">{t("ingestion.noVersion")}</p>;
  }
  return (
    <section className="card" aria-labelledby="ingestion-health-title">
      <div className="card-head">
        <h2 id="ingestion-health-title">{t("ingestion.health")}</h2>
      </div>
      {/* Des faits ÉTIQUETÉS, et non deux phrases en capitales (Gael, 05/11/2026) :
          `caption` est le style d'un mot posé au-dessus d'une valeur. Deux lignes de
          quatre-vingts caractères dans ce style perdaient la forme de leurs mots, et
          c'est toute la page de cet écran qui se lisait en majuscules. */}
      <dl className="facts">
        <div>
          <dt className="caption">{t("ingestion.captionVersion")}</dt>
          <dd className="value">
            {t("ingestion.version", {
              number: health.version_number,
              commit: (health.version_commit ?? "").slice(0, 12),
            })}
          </dd>
        </div>
        {health.version_served_at !== null && (
          <div>
            <dt className="caption">{t("ingestion.captionServed")}</dt>
            <dd className="value">{instant(health.version_served_at)}</dd>
          </div>
        )}
        <div>
          <dt className="caption">{t("ingestion.captionKeys")}</dt>
          <dd className="value">
            {t("ingestion.keys", { active: health.active_keys, unused: health.never_used_keys })}
          </dd>
        </div>
        <div>
          <dt className="caption">{t("ingestion.captionDeposits")}</dt>
          <dd className="value">
            {t("ingestion.deposits", {
              total: health.deposits_total,
              recent: health.deposits_recent,
            })}
            {" · "}
            {health.last_deposit_at === null
              ? t("ingestion.neverCalled")
              : t("ingestion.lastCall", { when: instant(health.last_deposit_at) })}
          </dd>
        </div>
      </dl>
      {health.unreadable_sources.length > 0 && (
        // Les taire ferait chercher une source absente alors qu'elle est là, et fautive.
        <p className="alert" role="status">
          {t("ingestion.unreadableSources", { sources: health.unreadable_sources.join(" · ") })}
        </p>
      )}
      {health.bulk_modes.length > 0 && (
        // Et on ne met AUCUN compteur sur une file qui n'existe pas : « pas encore
        // servi » est une information, « 0 en attente » est un mensonge.
        <p className="help">{t("ingestion.noBulkQueue")}</p>
      )}
    </section>
  );
}
