import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type Criterion, type Storage, useStorageObjects, useStorages } from "../api/storages";
import { StorageFilters } from "./StorageFilters";
import { StorageObjects } from "./StorageObjects";

/**
 * Les espaces de stockage de cette stack : ce que la version servie déclare, et ce que
 * les tables contiennent (Gael, 02/11/2026).
 *
 * Un seul écran pour les deux, et non une liste puis un détail : il y a peu de storages
 * par environnement, et ce qu'on vient y faire est chercher un objet. Un niveau de
 * navigation de plus n'apporterait qu'un clic.
 */
export function StoragesScreen() {
  const { t } = useTranslation();
  const storages = useStorages();
  const [choisi, setChoisi] = useState<string | null>(null);
  const storage = storages.data?.find((item) => item.name === choisi) ?? null;

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
        <h1 id="storages-title">{t("storages.title")}</h1>
      </div>
      <ul className="plain-list">
        {storages.data.map((item) => (
          <StorageRow
            key={item.name}
            storage={item}
            open={item.name === choisi}
            onOpen={() => setChoisi(item.name === choisi ? null : item.name)}
          />
        ))}
      </ul>
      {/* Aucune recherche offerte sur une table qui n'est pas posée : le formulaire
          promettrait un geste impossible, et le message de la ligne dit déjà
          pourquoi. */}
      {storage !== null && storage.refusal === null && storage.applied_at !== null && (
        <StorageSearch storage={storage} />
      )}
    </section>
  );
}

function StorageRow({
  storage,
  open,
  onOpen,
}: {
  storage: Storage;
  open: boolean;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <li className="row">
      <div className="row-main">
        <button type="button" className="row-title link" aria-expanded={open} onClick={onOpen}>
          {storage.label}
        </button>
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
      {open && storage.refusal === null && (
        <div className="row-detail">
          <p className="caption">
            {t("storages.key", { keys: storage.keys.join(" · ") })}
            {storage.version_number !== null &&
              ` · ${t("storages.version", { number: storage.version_number })}`}
          </p>
          {storage.indexes.length === 0 ? (
            <p className="help">{t("storages.noIndex")}</p>
          ) : (
            <ul className="plain-list">
              {storage.indexes.map((index) => (
                <li key={index.name} className="caption">
                  <span className="mono">{index.name}</span> —{" "}
                  {index.columns
                    .map(
                      (column) =>
                        storage.projections.find((p) => p.column === column)?.path ?? column,
                    )
                    .join(" · ")}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

/** La recherche dans le storage ouvert : ses filtres, et ce qu'ils rendent. */
function StorageSearch({ storage }: { storage: Storage }) {
  const { t } = useTranslation();
  const [criteria, setCriteria] = useState<Criterion[]>([]);
  const [page, setPage] = useState(1);
  const objects = useStorageObjects(storage.name, criteria, page, storage.applied_at !== null);

  function change(suivants: Criterion[]) {
    // Changer un critère ramène à la première page : rester en page 4 d'une recherche
    // qui n'a plus que deux pages afficherait un vide qu'on prendrait pour un résultat.
    setCriteria(suivants);
    setPage(1);
  }

  return (
    <section className="card" aria-labelledby="storage-search-title">
      <div className="card-head">
        <h2 id="storage-search-title">{t("storages.search", { label: storage.label })}</h2>
      </div>
      <StorageFilters storage={storage} criteria={criteria} onChange={change} />
      <StorageObjects storage={storage} query={objects} page={page} onPage={setPage} />
    </section>
  );
}
