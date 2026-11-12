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

/**
 * Une ligne du journal : le strict nécessaire pour RECONNAÎTRE un event.
 *
 * Réduite le 04/11/2026 (Gael : « les items sont trop gros »). Elle portait aussi la date
 * fonctionnelle, les objets concernés et toutes les propriétés — quatre à dix lignes par
 * event, si bien qu'un écran n'en montrait que trois. Or on PARCOURT un journal : ce
 * qu'il faut par ligne, c'est de quoi décider laquelle ouvrir. Le reste est à droite.
 */
function EventRow({
  event,
  selected,
  onOpen,
}: {
  event: JournalEvent;
  selected: boolean;
  onOpen: () => void;
}) {
  const instant = useInstant();

  // Le titre de la page est POSÉ SUR LE FOND, pas dans une carte (Gael, 05/11/2026) :
  // c'est ce que font tous les autres écrans des trois produits, et l'exception se
  // lisait comme un cadre de trop autour de la page entière.
  return (
    <li className={`row row-compact row-openable${selected ? " row-selected" : ""}`}>
      <div className="row-main">
        <button type="button" className="row-open mono" aria-current={selected} onClick={onOpen}>
          {event.type}
        </button>
        <div className="row-sub">
          {instant(event.written_at)} · {event.author_directory}/{event.author_subject}
        </div>
      </div>
    </li>
  );
}

/** Tout ce que la ligne ne porte plus, sur la ligne qu'on a choisie. */
function EventDetail({ event }: { event: JournalEvent | undefined }) {
  const { t } = useTranslation();
  const instant = useInstant();

  if (event === undefined) {
    return (
      <aside className="split-detail card-inset" aria-label={t("events.detail.title")}>
        <p className="help">{t("events.detail.none")}</p>
      </aside>
    );
  }
  const objets = event.objects
    .map((objet) => `${objet.kind}/${objet.id} #${objet.sequence}`)
    .join(" · ");
  return (
    <aside className="split-detail card-inset" aria-label={t("events.detail.title")}>
      <h3 className="mono">{event.type}</h3>
      {/* Les propriétés sont dans la MÊME liste de faits que les dates et les objets :
          elles décrivent l'event au même titre, et un titre de section au-dessus d'elles
          nommerait « propriétés » un filtre qui n'existe pas (ticket 461f0cf1). */}
      <dl className="facts">
        <div>
          <dt className="caption">{t("events.fields.writtenAt")}</dt>
          <dd className="value">{instant(event.written_at)}</dd>
        </div>
        <div>
          <dt className="caption">{t("events.fields.functionalAt")}</dt>
          <dd className="value">
            {instant(event.functional_at)}
            {/* La date métier est en fait celle de l'écriture : le dire, sinon le lecteur
                la prend pour une date fournie par l'appelant. */}
            {event.functional_at_source === "write_time" && (
              <span className="badge">{t("events.writeTime")}</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="caption">{t("events.fields.author")}</dt>
          <dd className="value">
            {event.author_directory}/{event.author_subject}
          </dd>
        </div>
        <div>
          <dt className="caption">{t("events.fields.category")}</dt>
          {/* Toujours montrée, contrairement aux trois champs facultatifs plus bas : la
              catégorie est NOT NULL en base, et c'est elle qui dira demain si le type est
              éditable dans l'IHM de configuration. Le numéro est la forme publiée ; le
              libellé n'est que son rendu, avec un repli qui le nomme pour qu'une huitième
              catégorie servie par le backend ne s'affiche pas vide. */}
          <dd className="value">
            {t([`events.categories.${event.category}`, "events.categories.unknown"], {
              number: event.category,
            })}
          </dd>
        </div>
        <div>
          <dt className="caption">{t("events.fields.objects")}</dt>
          <dd className="value">{objets === "" ? "—" : objets}</dd>
        </div>
        {/* Les champs de la racine commune ne sont montrés QUE renseignés : trois faits à
            « — » sur chaque event de l'atelier rallongeraient le détail que Gael a fait
            réduire le 04/11/2026, pour une information qui n'existe pas. */}
        {event.external_id !== null && (
          <div>
            <dt className="caption">{t("events.fields.externalId")}</dt>
            <dd className="value mono">{event.external_id}</dd>
          </div>
        )}
        {event.dedup_key !== null && (
          <div>
            <dt className="caption">{t("events.fields.dedupKey")}</dt>
            <dd className="value mono">{event.dedup_key}</dd>
          </div>
        )}
        {event.creation_date !== null && (
          <div>
            <dt className="caption">{t("events.fields.creationDate")}</dt>
            <dd className="value">{instant(event.creation_date)}</dd>
          </div>
        )}
        {Object.entries(event.properties).map(([clef, valeur]) => (
          <div key={clef}>
            <dt className="caption">{clef}</dt>
            <dd className="value mono">{JSON.stringify(valeur)}</dd>
          </div>
        ))}
      </dl>
    </aside>
  );
}

export function EventsScreen() {
  const { t } = useTranslation();
  const instant = useInstant();
  const [filtre, setFiltre] = useState<EventsFilter>({});
  const [page, setPage] = useState(1);
  // L'event ouvert à droite, par son identifiant. L'identifiant et non l'event : la page
  // suivante porte d'autres events, et un event recopié ici survivrait à la liste qui
  // l'a montré — on lirait le détail d'une ligne qui n'est plus à l'écran.
  const [ouvert, setOuvert] = useState<string | null>(null);
  const events = useEvents(filtre, page);

  function change(champ: keyof EventsFilter, valeur: string) {
    // Tout changement de filtre ramène à la première page : rester en page 3 d'un
    // résultat qui n'en a qu'une afficherait un journal vide sans dire pourquoi.
    setPage(1);
    setFiltre((precedent) => ({ ...precedent, [champ]: valeur }));
  }

  const total = events.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / EVENTS_PAGE_SIZE));
  const choisi = events.data?.events.find((event) => event.id === ouvert);

  return (
    <section aria-labelledby="events-title">
      <PageHead id="events-title" title={t("events.title")} lead={t("events.help")} />
      <div className="card">
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
                  {" · "}
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
              <div className="split">
                <ul className="card-list split-list">
                  {events.data.events.map((event) => (
                    <EventRow
                      key={event.id}
                      event={event}
                      selected={event.id === ouvert}
                      onOpen={() => setOuvert(event.id)}
                    />
                  ))}
                </ul>
                {/* Le détail est DÉRIVÉ de la page affichée : changer de page ou de filtre
                    le referme tout seul, au lieu de montrer un event absent de la liste. */}
                <EventDetail event={choisi} />
              </div>
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
      </div>
    </section>
  );
}
