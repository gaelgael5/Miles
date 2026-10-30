import { useTranslation } from "react-i18next";

import { type Timezone, useSetTimezonesActive, useTimezones } from "../api/timezones";

/**
 * Les fuseaux possibles d'un pays, dépliés depuis l'écran des pays.
 *
 * AUCUNE donnée nouvelle : la liste des possibles vient d'IANA et vit déjà en base, et la
 * route qui la sert existe depuis le référentiel des fuseaux. Ce composant est un écran sur
 * ce qui est là — c'est la décision de Gael du 30/10/2026, qui a écarté l'idée d'un second
 * état « retenu pour ce pays ».
 *
 * Il ne se monte QUE lorsqu'un pays est déplié, et c'est ce qui tient le critère du coût :
 * 249 pays dépliés d'office feraient 249 lectures pour une information que personne ne
 * regarde.
 */
export function CountryTimezones({ countrySlug }: { countrySlug: string }) {
  const { t, i18n } = useTranslation();
  const timezones = useTimezones({ culture: i18n.language, search: "", country: countrySlug });
  const change = useSetTimezonesActive();

  if (timezones.isPending) {
    return (
      <p className="muted" role="status">
        {t("countries.timezones.loading")}
      </p>
    );
  }
  if (timezones.data === undefined) {
    return (
      <p className="alert alert-danger" role="alert">
        {t("countries.timezones.unreachable")}
      </p>
    );
  }

  return (
    <div className="panel">
      <p className="help">{t("countries.timezones.help")}</p>
      <ul className="card-list plain-list">
        {timezones.data.map((zone) => (
          <ZoneRow
            key={zone.slug}
            zone={zone}
            countrySlug={countrySlug}
            pending={change.isPending}
            onToggle={() =>
              change.mutate({ slugs: [zone.slug], active: !zone.active })
            }
          />
        ))}
      </ul>
      {change.isError && (
        <p className="alert alert-danger" role="alert">
          {t("countries.timezones.changeFailed")}
        </p>
      )}
    </div>
  );
}

function ZoneRow({
  zone,
  countrySlug,
  pending,
  onToggle,
}: {
  zone: Timezone;
  countrySlug: string;
  pending: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  // Les AUTRES pays servis par ce fuseau. C'est eux qu'il faut nommer : l'activation est
  // globale, donc retenir `Europe/Brussels` depuis le Luxembourg le retient aussi pour la
  // Belgique et les Pays-Bas. Un administrateur qui ne le lit pas ici croira avoir fait un
  // geste local, et découvrira l'inverse sur un autre écran.
  const autres = zone.countries.filter((pays) => pays !== countrySlug);

  return (
    <li className="row">
      {/* Une bascule DIRECTE, et non « cocher puis appliquer » comme sur l'écran des
          fuseaux : un pays en a un le plus souvent, trois au plus souvent-pas. Une
          sélection groupée pour un élément unique demanderait deux gestes au lieu d'un. */}
      <label className="field-check row-main">
        <input type="checkbox" checked={zone.active} disabled={pending} onChange={onToggle} />
        <code>{zone.slug}</code> {zone.label}
        {autres.length > 0 && (
          <div className="row-sub">
            {t("countries.timezones.sharedWith", { countries: autres.join(", ") })}
          </div>
        )}
      </label>
      {zone.active && (
        <span className="badge badge-success">{t("countries.timezones.retained")}</span>
      )}
    </li>
  );
}
