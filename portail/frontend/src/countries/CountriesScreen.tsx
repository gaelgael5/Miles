import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PageHead } from "@miles/socle-web";

import { type Country, useCountries, useSetCountriesActive } from "../api/countries";
import { CountryTimezones } from "./CountryTimezones";

function CountryRow({
  country,
  selected,
  onToggle,
}: {
  country: Country;
  selected: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  // Déplié à la demande, et c'est ce qui tient le coût : le panneau ne se monte que là,
  // donc les fuseaux d'un pays ne sont lus que si quelqu'un les regarde.
  const [deplie, setDeplie] = useState(false);
  return (
    <li className="row">
      <label className="field-check row-main">
        <input type="checkbox" checked={selected} onChange={onToggle} />
        {/* Le libellé d'abord, les codes ensuite : on cherche « Allemagne », on recopie
            « DEU ». L'alpha-2 est là parce que les systèmes tiers l'emploient. */}
        {country.label} <code>{country.slug}</code>{" "}
        <span className="muted">{country.alpha2}</span>
      </label>
      {country.active && <span className="badge badge-success">{t("countries.active")}</span>}
      <div className="actions row-actions">
        <button
          type="button"
          className="btn btn-secondary"
          aria-expanded={deplie}
          onClick={() => setDeplie((ouvert) => !ouvert)}
        >
          {t("countries.timezones.open")}
        </button>
      </div>
      {deplie && <CountryTimezones countrySlug={country.slug} />}
    </li>
  );
}

/**
 * Pays de l'installation : la liste est donnée, on n'y fait qu'activer et désactiver.
 *
 * Le même écran que les cultures, et c'est voulu — c'est le dispositif que Gael a tranché
 * le 15/10/2026 pour un référentiel donné, et deux écrans qui font la même chose doivent se
 * lire pareil. Une seule différence, et elle se justifie : le filtre est envoyé AU SERVEUR,
 * parce que c'est lui qui dérive les libellés et que seul lui peut faire correspondre
 * « allemagne » à `DEU`.
 *
 * L'écran ne s'appelle pas « référentiel » : le mot désigne déjà trois autres choses dans
 * ce produit — référentiels d'objets ingérés, référentiels de mapping de git, storages.
 */
export function CountriesScreen() {
  const { t, i18n } = useTranslation();
  const [filter, setFilter] = useState("");
  // La sélection survit au filtre : l'action porte sur ce qui est COCHÉ, pas sur ce qui
  // est affiché, pour qu'un filtre modifié entre-temps n'élargisse rien.
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const countries = useCountries({ culture: i18n.language, search: filter });
  const change = useSetCountriesActive();
  const visible = countries.data ?? [];

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
    <section aria-labelledby="countries-title">
      <PageHead id="countries-title" title={t("countries.title")} lead={t("countries.intro")} />
      <div className="card">
        <label className="field">
          {t("countries.filter")}
          <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </label>
        <div className="actions">
          <span className="muted">{t("countries.selected", { count: selected.size })}</span>
          <button
            type="button"
            className="btn btn-primary"
            disabled={selected.size === 0 || change.isPending}
            onClick={() => apply(true)}
          >
            {t("countries.activate")}
          </button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={selected.size === 0 || change.isPending}
            onClick={() => apply(false)}
          >
            {t("countries.deactivate")}
          </button>
        </div>
        {/* Dit, et pas seulement vrai : un administrateur qui croit perdre quelque chose
            en désactivant ne désactive pas. */}
        <p className="alert">{t("countries.keepRows")}</p>
      </div>
      {change.isError && (
        <p className="alert alert-danger" role="alert">
          {t("countries.errors.change")}
        </p>
      )}
      {countries.isPending && (
        <p className="muted" role="status">
          {t("countries.loading")}
        </p>
      )}
      {countries.isError && (
        <p className="alert alert-danger" role="alert">
          {t("countries.errors.unreachable")}
        </p>
      )}
      {countries.isSuccess && visible.length === 0 && (
        <p className="muted" role="status">
          {t("countries.noMatch", { filter })}
        </p>
      )}
      {visible.length > 0 && (
        <ul className="card-list plain-list">
          {visible.map((country) => (
            <CountryRow
              key={country.slug}
              country={country}
              selected={selected.has(country.slug)}
              onToggle={() => toggle(country.slug)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
