import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Me } from "../api/auth";
import { usePublicCultures } from "../api/cultures";
import { usePreferences, useSetLanguage } from "../api/preferences";
import { UI_LANGUAGES, applyLanguage } from "../i18n/i18n";
import { PageHead } from "../layout/PageHead";

function Identity({ me }: { me: Me }) {
  const { t } = useTranslation();
  const rows: [string, string][] = [
    [t("profile.fields.kind"), t(`profile.kind.${me.kind}`)],
    [t("profile.fields.name"), me.username],
    [t("profile.fields.email"), me.email ?? "—"],
  ];
  if (me.kind === "oidc") {
    rows.push([t("profile.fields.directory"), me.directory ?? "—"]);
    rows.push([t("profile.fields.subject"), me.subject]);
  }
  return (
    <section className="card" aria-labelledby="profile-identity">
      <h2 id="profile-identity">{t("profile.identity")}</h2>
      <dl className="facts">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd className={label === t("profile.fields.subject") ? "mono" : undefined}>{value}</dd>
          </div>
        ))}
      </dl>
      {me.root_admin && <span className="badge badge-accent">{t("profile.rootAdmin")}</span>}
    </section>
  );
}

function Language() {
  const { t, i18n } = useTranslation();
  const cultures = usePublicCultures();
  const preferences = usePreferences();
  const choose = useSetLanguage();
  // Seules les cultures actives que l'IHM sait afficher sont proposées.
  const offered = (cultures.data ?? []).filter((c) => UI_LANGUAGES.includes(c.code));

  function select(code: string) {
    choose.mutate(code, { onSuccess: (saved) => applyLanguage(saved.language) });
  }

  return (
    <section className="card" aria-labelledby="profile-language">
      <h2 id="profile-language">{t("profile.language")}</h2>
      <label className="field">
        {t("profile.fields.language")}
        <select
          value={preferences.data?.language ?? i18n.language}
          disabled={!cultures.isSuccess || choose.isPending}
          onChange={(e) => select(e.target.value)}
        >
          {offered.map((c) => (
            <option key={c.code} value={c.code}>
              {c.label_native} ({c.code})
            </option>
          ))}
        </select>
      </label>
      <p className="help">{t("profile.languageHelp")}</p>
      {choose.isError && (
        <p className="alert" role="alert">
          {t("profile.errors.language")}
        </p>
      )}
    </section>
  );
}

/**
 * Mon profil (ticket 0a52596d) : ce que tout produit Miles sait dire de la personne
 * connectée — son identité de session et la langue retenue pour son compte.
 *
 * Les sections propres au produit arrivent en `children` plutôt que par une liste de
 * composants déclarée ici : le socle n'a pas à connaître les écrans de ses consommateurs,
 * et c'est le produit qui décide de leur ordre. L'écran est répliqué dans les trois
 * produits (cadrage, « À quel produit appartient chaque écran »), et le rapprochement
 * d'identités NE TRAVERSE PAS les produits — ce qui est lié ici ne l'est qu'ici.
 */
export function ProfileShell({ me, children }: { me: Me; children?: ReactNode }) {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="profile-title">
      <PageHead id="profile-title" title={t("profile.title")} lead={t("profile.intro")} />
      <Identity me={me} />
      <Language />
      {children}
    </section>
  );
}
