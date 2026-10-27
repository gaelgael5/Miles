import { useTranslation } from "react-i18next";

import { useMyShelves } from "../api/holds";

/**
 * Mes branches rangées (story fd1eb7da, critère 5) : après un déverrouillage, la personne
 * retrouve ici son travail non publié, et sait que reprendre la main le fusionnera.
 */
export function ShelvesSection() {
  const { t, i18n } = useTranslation();
  const shelves = useMyShelves();
  if (shelves.isSuccess && shelves.data.length === 0) {
    return null;
  }
  return (
    <section className="card" aria-labelledby="profile-shelves">
      <h2 id="profile-shelves">{t("profile.shelves.title")}</h2>
      {shelves.isError && (
        <p className="alert" role="alert">
          {t("profile.shelves.error")}
        </p>
      )}
      {shelves.isSuccess && (
        <>
          <p className="help">{t("profile.shelves.help")}</p>
          <ul className="plain-list">
            {shelves.data.map((s) => (
              <li key={`${s.workspace_id}/${s.slug}`}>
                {t("profile.shelves.item", {
                  workspace: s.workspace_name,
                  branch: s.slug,
                  date: new Date(s.shelved_at).toLocaleString(i18n.language),
                })}{" "}
                <span className="mono">{s.shelf_branch}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
