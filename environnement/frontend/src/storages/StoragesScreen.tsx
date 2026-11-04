import { useTranslation } from "react-i18next";

import { type Storage, useStorages } from "../api/storages";

/**
 * Les espaces de stockage que la version servie déclare (Gael, 02/11/2026).
 *
 * Ce que cette page montre, c'est la DÉCLARATION : quels espaces existent, sur quel
 * modèle, dans quelle table, et lesquels sont refusés. Les objets de chacun sont sur SA
 * page, que le menu ouvre (Gael, 04/11/2026) — tenir la recherche ici faisait lire les
 * colonnes d'un espace en cherchant dans un autre.
 */
export function StoragesScreen() {
  const { t } = useTranslation();
  const storages = useStorages();

  if (storages.isPending) {
    return (
      <p className="muted" role="status">
        {t("storages.loading")}
      </p>
    );
  }
  if (storages.isError) {
    return (
      <p className="alert" role="alert">
        {t("storages.unreadable")}
      </p>
    );
  }
  if (storages.data.length === 0) {
    // Ni une erreur ni une panne : une stack dont la version ne déclare aucun storage, ou
    // qui n'héberge encore aucune version. Le dire, plutôt qu'un écran vide.
    return <p className="help">{t("storages.none")}</p>;
  }
  return (
    <section aria-labelledby="storages-title">
      <div className="page-head">
        <div>
          <h1 id="storages-title">{t("storages.title")}</h1>
          <p className="lead">{t("storages.lead")}</p>
        </div>
      </div>
      <ul className="card-list">
        {storages.data.map((item) => (
          <StorageRow key={item.name} storage={item} />
        ))}
      </ul>
    </section>
  );
}

function StorageRow({ storage }: { storage: Storage }) {
  const { t } = useTranslation();

  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{storage.label}</div>
        <div className="row-sub">
          <span className="mono">{storage.model}</span>
          {storage.refusal === null && (
            <>
              {" · "}
              <span className="mono">
                {storage.schema_name}.{storage.table_name}
              </span>
            </>
          )}
        </div>
      </div>
      {/* Un storage REFUSÉ apparaît dans la même liste que les autres, et dit pourquoi.
          L'écarter de la liste le rendrait invisible : on chercherait une déclaration
          absente alors qu'elle est là, et fautive. */}
      {storage.refusal !== null && (
        <p className="alert row-detail" role="status">
          {t(`storages.refusals.${storage.refusal}`, {
            defaultValue: t("storages.refusals.unknown", { code: storage.refusal }),
          })}
          {storage.refusal_detail !== null && (
            <>
              {" "}
              <span className="mono">{storage.refusal_detail}</span>
            </>
          )}
        </p>
      )}
      {storage.refusal === null && storage.applied_at === null && (
        // Déclaré mais pas posé : distinct d'une table vide, et il faut le dire —
        // sinon une recherche sans résultat se lit comme « aucun objet ».
        <p className="muted row-detail">{t("storages.notApplied")}</p>
      )}
    </li>
  );
}
