import { useTranslation } from "react-i18next";

import { useInstant } from "@miles/socle-web";

import { type Health, useIngestionHealth } from "../api/ingestion";
import { IngestionCalls } from "./IngestionCalls";
import { IngestionMethods } from "./IngestionMethods";

/**
 * L'écran du service d'ingestion : son état de santé, et le journal des appels
 * (Gael, 02/11/2026).
 *
 * « L'état de santé », interrogé, c'était « les deux » : le point d'entrée répond, et
 * les dépôts de masse avancent. **La seconde moitié n'a rien à mesurer**, et cet écran
 * le dit — le mode fichier n'est pas encore servi, donc il n'existe aucune file. Un
 * compteur à zéro laisserait croire qu'on surveille quelque chose.
 */
export function IngestionScreen() {
  const { t } = useTranslation();
  const health = useIngestionHealth();

  if (health.isPending) {
    return (
      <p className="muted" role="status">
        {t("ingestion.loading")}
      </p>
    );
  }
  if (health.isError) {
    return (
      <p className="alert" role="alert">
        {t("ingestion.unreadable")}
      </p>
    );
  }
  return (
    <section aria-labelledby="ingestion-title">
      <div className="page-head">
        <h1 id="ingestion-title">{t("ingestion.title")}</h1>
      </div>
      <ServiceHealth health={health.data} />
      {/* Les méthodes AVANT le journal : on vient ici pour savoir quoi appeler, et
          le journal répond à « qu'est-ce qui est arrivé », qui vient après. */}
      <IngestionMethods />
      <IngestionCalls />
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
      <p className="caption">
        {t("ingestion.version", {
          number: health.version_number,
          commit: (health.version_commit ?? "").slice(0, 12),
        })}
        {health.version_served_at !== null &&
          ` · ${t("ingestion.servedAt", {
            when: instant(health.version_served_at),
          })}`}
      </p>
      <p className="caption">
        {t("ingestion.keys", { active: health.active_keys, unused: health.never_used_keys })}
        {" · "}
        {t("ingestion.deposits", {
          total: health.deposits_total,
          recent: health.deposits_recent,
        })}
        {" · "}
        {health.last_deposit_at === null
          ? t("ingestion.neverCalled")
          : t("ingestion.lastCall", {
              when: instant(health.last_deposit_at),
            })}
      </p>
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
