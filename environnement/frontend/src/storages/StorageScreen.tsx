import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { type Criterion, type Storage, useStorageObjects, useStorages } from "../api/storages";
import { StorageFilters, emptyCriteria } from "./StorageFilters";
import { StorageObjects } from "./StorageObjects";

/**
 * Ce qui a cessé de bouger depuis `delai`, pour ne pas chercher à chaque frappe.
 *
 * Nécessaire depuis que chaque colonne porte son filtre : taper « S-001 » lançait cinq
 * recherches, et « contient » se résout par un parcours que l'index de la clé ne sert
 * pas. La saisie, elle, reste immédiate — c'est la REQUÊTE qui attend.
 */
function useDebounced<T>(valeur: T, delai = 300): T {
  const [retardee, setRetardee] = useState(valeur);

  useEffect(() => {
    const minuteur = setTimeout(() => setRetardee(valeur), delai);
    return () => clearTimeout(minuteur);
  }, [valeur, delai]);

  return retardee;
}

/**
 * UN espace de stockage : ce que la version en déclare, et ce que sa table contient
 * (Gael, 04/11/2026 — « dans chaque objet on affiche les objets respectifs »).
 *
 * Page à part depuis que le menu liste les espaces. La recherche d'un espace tenait
 * auparavant sous la liste de tous : avec plusieurs espaces et une table par espace, on
 * cherchait dans l'un en lisant les colonnes d'un autre.
 */
export function StorageScreen({ name }: { name: string }) {
  const { t } = useTranslation();
  const storages = useStorages();
  const storage = storages.data?.find((item) => item.name === name);

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
  if (storage === undefined) {
    // La version servie ne déclare plus cet espace : le menu l'a retiré, et cette page
    // est restée ouverte. Le dire, plutôt que de rendre un écran vide.
    return <p className="help">{t("storages.gone", { name })}</p>;
  }
  return (
    <section aria-labelledby="storage-title">
      <div className="page-head">
        <div>
          <h1 id="storage-title">{storage.label}</h1>
          <p className="lead">
            <span className="mono">{storage.model}</span>
            {storage.refusal === null && (
              <>
                {" · "}
                <span className="mono">
                  {storage.schema_name}.{storage.table_name}
                </span>
              </>
            )}
          </p>
        </div>
      </div>
      <StorageDeclaration storage={storage} />
      {/* Aucune recherche offerte sur une table qui n'est pas posée : le formulaire
          promettrait un geste impossible, et le message ci-dessus dit déjà pourquoi. */}
      {storage.refusal === null && storage.applied_at !== null && (
        <StorageSearch storage={storage} />
      )}
    </section>
  );
}

/** Ce que le paramétrage déclare de cet espace : sa clé, ses index, ses refus. */
function StorageDeclaration({ storage }: { storage: Storage }) {
  const { t } = useTranslation();

  return (
    <>
      {/* Un espace REFUSÉ garde sa page et dit pourquoi : sans elle, on chercherait une
          déclaration absente alors qu'elle est là, et fautive. */}
      {storage.refusal !== null && (
        <p className="alert" role="status">
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
        <p className="muted">{t("storages.notApplied")}</p>
      )}
      {storage.refusal === null && (
        <>
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
        </>
      )}
    </>
  );
}

/** La recherche dans cet espace : ses filtres, et ce qu'ils rendent. */
function StorageSearch({ storage }: { storage: Storage }) {
  const { t } = useTranslation();
  // Un critère par propriété filtrable, tous vides : la barre de filtres les porte
  // comme autant de colonnes, et il n'y a plus de critère à ajouter avant de chercher.
  const [criteria, setCriteria] = useState<Criterion[]>(() => emptyCriteria(storage));
  const [page, setPage] = useState(1);
  const cherches = useDebounced(criteria);
  const objects = useStorageObjects(storage.name, cherches, page, storage.applied_at !== null);

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
