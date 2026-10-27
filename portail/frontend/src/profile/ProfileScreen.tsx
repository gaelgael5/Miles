import { useTranslation } from "react-i18next";

import type { Me } from "../api/auth";
import { usePublicCultures } from "../api/cultures";
import { usePreferences, useSetLanguage } from "../api/preferences";
import { useWorkspaces } from "../api/workspaces";
import { PORTAL_LANGUAGES, applyLanguage } from "../i18n/i18n";
import { PageHead } from "../layout/PageHead";
import { BranchPicker } from "../workspaces/BranchPicker";
import { ActorIdentitySection } from "./ActorIdentitySection";
import { GitIdentitiesSection } from "./GitIdentitiesSection";
import { OAuthGrantsSection } from "./OAuthGrantsSection";
import { ShelvesSection } from "./ShelvesSection";

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
  // Seules les cultures actives que le portail sait afficher sont proposées.
  const offered = (cultures.data ?? []).filter((c) => PORTAL_LANGUAGES.includes(c.code));

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

function BranchViews() {
  const { t } = useTranslation();
  const workspaces = useWorkspaces();
  const withBranch = (workspaces.data ?? []).filter((w) => w.work_branch !== null);
  return (
    <section className="card" aria-labelledby="profile-branches">
      <h2 id="profile-branches">{t("profile.branches")}</h2>
      {workspaces.isSuccess && withBranch.length === 0 && (
        <p className="muted">{t("profile.noBranch")}</p>
      )}
      <ul className="card-list plain-list">
        {withBranch.map((w) => (
          <li key={w.id} className="row">
            <div className="row-main">
              <div className="row-title">{w.name}</div>
            </div>
            <BranchPicker workspace={w} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Mon profil (ticket 0a52596d) : qui je suis pour le portail, et mes préférences. */
export function ProfileScreen({ me }: { me: Me }) {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="profile-title">
      <PageHead id="profile-title" title={t("profile.title")} lead={t("profile.intro")} />
      <Identity me={me} />
      <Language />
      <GitIdentitiesSection />
      <ActorIdentitySection />
      <OAuthGrantsSection />
      <ShelvesSection />
      {/* Les workspaces sont réservés à l'administrateur tant que les rôles manquent. */}
      {me.root_admin && <BranchViews />}
    </section>
  );
}
