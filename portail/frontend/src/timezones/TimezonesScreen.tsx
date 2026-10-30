import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PageHead } from "@miles/socle-web";

import { type Timezone, useSetTimezonesActive, useTimezones } from "../api/timezones";

function TimezoneRow({
  timezone,
  selected,
  onToggle,
}: {
  timezone: Timezone;
  selected: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  return (
    <li className="row">
      <label className="field-check row-main">
        <input type="checkbox" checked={selected} onChange={onToggle} />
        {/* L'identifiant IANA d'abord : c'est lui qui désigne le fuseau. Le libellé de
            CLDR est un nom de métazone — « heure d'Europe centrale » vaut pour Paris,
            Berlin et Madrid —, donc il ne suffit pas à distinguer trois lignes. */}
        <code>{timezone.slug}</code> {timezone.label}
        {/* Tous les pays, dans l'ordre d'IANA : « Europe/Paris » en a deux. */}
        <div className="row-sub">{timezone.countries.join(", ")}</div>
      </label>
      {timezone.active && <span className="badge badge-success">{t("timezones.active")}</span>}
    </li>
  );
}

/**
 * Fuseaux horaires de l'installation : la liste est donnée, on n'y fait qu'activer.
 *
 * Le jumeau de l'écran des pays, délibérément : deux écrans qui font la même chose doivent
 * se lire pareil. Une seule chose en plus — le filtre par pays, qui est l'usage pour
 * lequel le lien vers les pays existe.
 */
export function TimezonesScreen() {
  const { t, i18n } = useTranslation();
  const [filter, setFilter] = useState("");
  const [country, setCountry] = useState("");
  // La sélection survit aux filtres : l'action porte sur ce qui est COCHÉ, pas sur ce qui
  // est affiché, pour qu'un filtre modifié entre-temps n'élargisse rien.
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const timezones = useTimezones({ culture: i18n.language, search: filter, country });
  const change = useSetTimezonesActive();
  const visible = timezones.data ?? [];

  function toggle(slug: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(slug)) {
        next.delete(slug);
      } else {
        next.add(slug);
      }
      return next;
    });
  }

  function apply(active: boolean) {
    change.mutate({ slugs: [...selected], active }, { onSuccess: () => setSelected(new Set()) });
  }

  return (
    <section aria-labelledby="timezones-title">
      <PageHead id="timezones-title" title={t("timezones.title")} lead={t("timezones.intro")} />
      <div className="card">
        <label className="field">
          {t("timezones.filter")}
          <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </label>
        <label className="field">
          {t("timezones.byCountry")}
          {/* Saisi en alpha-3, comme le slug du référentiel des pays : c'est le code
              qu'une procédure écrit, et celui que l'autre écran affiche. */}
          <input
            type="search"
            value={country}
            maxLength={3}
            onChange={(e) => setCountry(e.target.value.toUpperCase())}
          />
        </label>
        <div className="actions">
          <span className="muted">{t("timezones.selected", { count: selected.size })}</span>
          <button
            type="button"
            className="btn btn-primary"
            disabled={selected.size === 0 || change.isPending}
            onClick={() => apply(true)}
          >
            {t("timezones.activate")}
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={selected.size === 0 || change.isPending}
            onClick={() => apply(false)}
          >
            {t("timezones.deactivate")}
          </button>
        </div>
        <p className="alert">{t("timezones.keepRows")}</p>
      </div>
      {change.isError && (
        <p className="alert alert-danger" role="alert">
          {t("timezones.errors.change")}
        </p>
      )}
      {timezones.isPending && (
        <p className="muted" role="status">
          {t("timezones.loading")}
        </p>
      )}
      {timezones.isError && (
        <p className="alert alert-danger" role="alert">
          {t("timezones.errors.unreachable")}
        </p>
      )}
      {timezones.isSuccess && visible.length === 0 && (
        <p className="muted" role="status">
          {t("timezones.noMatch")}
        </p>
      )}
      {visible.length > 0 && (
        <ul className="card-list plain-list">
          {visible.map((timezone) => (
            <TimezoneRow
              key={timezone.slug}
              timezone={timezone}
              selected={selected.has(timezone.slug)}
              onToggle={() => toggle(timezone.slug)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
