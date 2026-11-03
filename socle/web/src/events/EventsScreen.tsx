import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type EventsFilter,
  type JournalEvent,
  EVENTS_PAGE_SIZE,
  useEvents,
} from "../api/events";
import { ApiError } from "../api/http";
import { useInstant } from "../i18n/instants";
import { PageHead } from "../layout/PageHead";

function refusalKey(error: unknown): string {
  if (error instanceof ApiError && error.status === 400) {
    const detail = error.detail as { code?: string } | undefined;
    if (detail?.code === "bornes_inversees") {
      return "events.errors.window";
    }
    if (detail?.code === "auteur_incomplet" || detail?.code === "objet_incomplet") {
      return "events.errors.pair";
    }
  }
  return "events.errors.unexpected";
}

function EventRow({ event }: { event: JournalEvent }) {
  const { t } = useTranslation();
  const instant = useInstant();
  const objets = event.objects
    .map((objet) => `${objet.kind}/${objet.id} #${objet.sequence}`)
    .join(" · ");
  const proprietes = Object.entries(event.properties);
  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">
          <span className="mono">{event.type}</span>
        </div>
        <div className="row-sub">
          {instant(event.written_at)} · {event.author_directory}/{event.author_subject}
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("events.fields.functionalAt")}</div>
        <div className="value">
          {instant(event.functional_at)}
          {/* La date métier est en fait celle de l'écriture : le dire, sinon le lecteur la
              prend pour une date fournie par l'appelant. */}
          {event.functional_at_source === "write_time" && (
            <span className="badge">{t("events.writeTime")}</span>
          )}
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("events.fields.objects")}</div>
        <div className="value">{objets === "" ? "—" : objets}</div>
      </div>
      {proprietes.length > 0 && (
        // Affichées, jamais filtrables : rien ne déclare quelles clefs d'un type d'event
        // sont interrogeables, et où cette déclaration vit n'est pas tranché (ticket
        // 461f0cf1). Un filtre écrit ici devancerait cette décision.
        <dl className="facts row-detail">
          {proprietes.map(([clef, valeur]) => (
            <div key={clef}>
              <dt className="caption">{clef}</dt>
              <dd className="value mono">{JSON.stringify(valeur)}</dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  );
}

export function EventsScreen() {
  const { t } = useTranslation();
  const instant = useInstant();
  const [filtre, setFiltre] = useState<EventsFilter>({});
  const [page, setPage] = useState(1);
  const events = useEvents(filtre, page);

  function change(champ: keyof EventsFilter, valeur: string) {
    // Tout changement de filtre ramène à la première page : rester en page 3 d'un
    // résultat qui n'en a qu'une afficherait un journal vide sans dire pourquoi.
    setPage(1);
    setFiltre((precedent) => ({ ...precedent, [champ]: valeur }));
  }

  const total = events.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / EVENTS_PAGE_SIZE));

  return (
    <section className="card" aria-labelledby="events-title">
      <PageHead id="events-title" title={t("events.title")} lead={t("events.help")} />
      <div className="filters">
        <label className="field">
          <span>{t("events.filters.type")}</span>
          <input
            value={filtre.type ?? ""}
            onChange={(e) => change("type", e.target.value)}
            placeholder={t("events.filters.typePlaceholder")}
          />
        </label>
        <label className="field">
          <span>{t("events.filters.writtenFrom")}</span>
          <input
            type="date"
            value={filtre.written_from ?? ""}
            onChange={(e) => change("written_from", e.target.value)}
          />
        </label>
        <label className="field">
          <span>{t("events.filters.writtenTo")}</span>
          <input
            type="date"
            value={filtre.written_to ?? ""}
            onChange={(e) => change("written_to", e.target.value)}
          />
        </label>
      </div>
      {events.isError && (
        <p className="alert" role="alert">
          {t(refusalKey(events.error))}
        </p>
      )}
      {events.isSuccess && (
        <>
          <p className="help" role="status">
            {t("events.found", { count: events.data.total })}
            {/* La fenêtre par défaut se DIT : sans cette phrase, l'écran montre sept jours
                en laissant croire qu'il montre tout le journal. */}
            {events.data.window.defaulted && (
              <>
                {" "}
                {t("events.defaultWindow", {
                  start: instant(events.data.window.start),
                  end: instant(events.data.window.end),
                })}
              </>
            )}
          </p>
          {events.data.missing_sequences.length > 0 && (
            // Une histoire incomplète se signale. Avec une rétention glissante, c'est le
            // cas NORMAL et non une anomalie : les premiers events ont été purgés.
            <p className="alert" role="status">
              {t("events.missingSequences", {
                sequences: events.data.missing_sequences.join(", "),
              })}
            </p>
          )}
          {events.data.events.length === 0 ? (
            <p className="muted">{t("events.none")}</p>
          ) : (
            <ul className="card-list">
              {events.data.events.map((event) => (
                <EventRow key={event.id} event={event} />
              ))}
            </ul>
          )}
          {pages > 1 && (
            <div className="actions">
              <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                {t("events.previous")}
              </button>
              <span className="muted">{t("events.page", { page, pages })}</span>
              <button type="button" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                {t("events.next")}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
