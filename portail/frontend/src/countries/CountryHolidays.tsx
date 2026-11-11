import { useTranslation } from "react-i18next";

import { ApiError, useCalendarDate } from "@miles/socle-web";

import { type HolidayDay, useCountryHolidays } from "../api/countries";

/**
 * Les jours fériés d'un pays, dépliés depuis l'écran des pays (Gael, 11/11/2026).
 *
 * Deux choses, et elles répondent à la même question — « d'où ça sort ? » : le LIEN vers le
 * fichier de règles du dépôt calendarium, et les JOURS que ces règles produisent sur les
 * douze prochains mois. Miles ne recopie aucune règle ; il montre la source et son effet.
 *
 * Il ne se monte QUE lorsqu'un pays est déplié, comme le panneau des fuseaux : 249 pays
 * dépliés d'office feraient 249 calculs que personne ne regarde.
 */
export function CountryHolidays({ countrySlug }: { countrySlug: string }) {
  const { t } = useTranslation();
  const holidays = useCountryHolidays(countrySlug);
  const jour = useCalendarDate();

  if (holidays.isPending) {
    return (
      <p className="muted" role="status">
        {t("countries.holidays.loading")}
      </p>
    );
  }
  if (holidays.isError) {
    // Deux refus distincts, deux gestes distincts. `regles_indisponibles` dit que la base
    // et le paquet installé ne parlent pas du même référentiel : le geste est d'aller
    // regarder la version de calendarium, et un message générique n'enverrait nulle part.
    const indisponible =
      holidays.error instanceof ApiError &&
      (holidays.error.payload as { reason?: unknown } | undefined)?.reason ===
        "regles_indisponibles";
    return (
      <p className="alert alert-danger" role="alert">
        {t(indisponible ? "countries.holidays.unavailable" : "countries.holidays.unreachable")}
      </p>
    );
  }

  const regles = holidays.data;
  // Le nom du fichier seul dans le libellé du lien : l'URL entière fait quatre-vingts
  // caractères et noierait la ligne, alors que `date_France.json` dit exactement ce qu'on
  // va ouvrir. L'URL complète reste dans l'infobulle et dans l'adresse du lien.
  const fichier = regles.source_url.split("/").pop() ?? regles.source_url;

  return (
    <div className="panel">
      <p className="help">{t("countries.holidays.help")}</p>
      <dl className="facts">
        <dt>{t("countries.holidays.source")}</dt>
        <dd>
          <a
            href={regles.page_url}
            title={regles.source_url}
            // `noreferrer` autant que `noopener` : le lien sort du portail vers un site
            // tiers, et rien de l'adresse d'origine n'a à l'accompagner.
            target="_blank"
            rel="noreferrer noopener"
          >
            {t("countries.holidays.sourceOpen", { file: fichier })}
          </a>
        </dd>
      </dl>
      {/* La fenêtre est celle que le SERVEUR annonce, pas une que l'écran recalculerait :
          deux calculs de « douze prochains mois » de part et d'autre auraient fini par ne
          pas dire la même chose. */}
      <p className="muted">
        {t("countries.holidays.window", {
          start: jour(regles.start),
          end: jour(regles.end),
        })}
      </p>
      {regles.days.length === 0 ? (
        <p className="muted">{t("countries.holidays.none")}</p>
      ) : (
        <ul className="card-list plain-list">
          {regles.days.map((day) => (
            <DayRow key={`${day.date}-${day.name}`} day={day} />
          ))}
        </ul>
      )}
    </div>
  );
}

function DayRow({ day }: { day: HolidayDay }) {
  const { t } = useTranslation();
  const jour = useCalendarDate();
  return (
    <li className="row">
      <span className="row-main">
        <strong>{jour(day.date)}</strong> {day.name}
        {/* Le report n'est dit que lorsqu'il a lieu : écrire « reporté au 14 juillet » sur
            une fête du 14 juillet ferait douter de ce que la ligne annonce. */}
        {day.shifted && (
          <div className="row-sub">
            {t("countries.holidays.shifted", { observed: jour(day.observed) })}
          </div>
        )}
      </span>
      {/* Chômé ou non, TOUJOURS dit, et non seulement quand c'est vrai : une
          commémoration calculée sans être un jour de congé serait lue comme un jour de
          fermeture, et un point relais fermerait pour rien. */}
      <span className={day.free ? "badge badge-success" : "badge"}>
        {t(day.free ? "countries.holidays.free" : "countries.holidays.notFree")}
      </span>
    </li>
  );
}
