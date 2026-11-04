import { useState } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { ApiError, useInstant } from "@miles/socle-web";
import { readableKey } from "../api/storageKey";
import type { ObjectPage, Storage, StorageObject } from "../api/storages";

type Detail = { code?: string; detail?: string };

/**
 * Le refus d'une recherche, NOMMÉ. Un critère sur une propriété non déclarée est une
 * erreur d'appel, pas une recherche sans résultat : les confondre ferait conclure
 * « aucun objet » là où le filtre lui-même est fautif.
 */
function SearchRefusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const detail =
    error instanceof ApiError && typeof error.detail === "object"
      ? (error.detail as Detail)
      : null;
  const code = detail?.code ?? "unexpected";
  return (
    <div className="alert" role="alert">
      <p>
        {t(`storages.searchErrors.${code}`, {
          property: detail?.detail ?? "",
          defaultValue: t("storages.searchErrors.unexpected"),
        })}
      </p>
    </div>
  );
}

/**
 * Le modèle de l'objet choisi, à droite de la table (Gael, 04/11/2026).
 *
 * C'est ce qu'on vient chercher : la table dit QUELS objets répondent, le panneau dit ce
 * que l'un d'eux CONTIENT. Rendre le modèle sous chaque ligne — ce que faisait l'écran —
 * donnait vingt lignes de JSON par objet, et la table cessait d'être parcourable.
 */
function ObjectDetail({ objet }: { objet: StorageObject | undefined }) {
  const { t } = useTranslation();
  const instant = useInstant();

  if (objet === undefined) {
    return (
      <aside className="split-detail card-inset" aria-label={t("storages.detail.title")}>
        <p className="help">{t("storages.detail.none")}</p>
      </aside>
    );
  }
  return (
    <aside className="split-detail card-inset" aria-label={t("storages.detail.title")}>
      <h3 className="mono">{readableKey(objet.cle)}</h3>
      <p className="caption">
        {t("storages.seen", { date: instant(objet.vu_le) })}
        {" · "}
        {t("storages.changed", { date: instant(objet.modifie_le) })}
        {" · "}
        {t(`storages.origins.${objet.origine}`, { defaultValue: objet.origine })}
      </p>
      <pre className="mono detail-json">{JSON.stringify(objet.objet, null, 2)}</pre>
    </aside>
  );
}

export function StorageObjects({
  storage,
  query,
  page,
  onPage,
}: {
  storage: Storage;
  query: UseQueryResult<ObjectPage>;
  page: number;
  onPage: (page: number) => void;
}) {
  const { t } = useTranslation();
  const instant = useInstant();
  // L'objet ouvert, par sa clé. La clé et non l'objet : la page suivante en porte
  // d'autres, et un objet recopié ici survivrait à la table qui l'a montré.
  const [ouvert, setOuvert] = useState<string | null>(null);

  if (query.isPending) {
    return (
      <p className="muted" role="status">
        {t("storages.searching")}
      </p>
    );
  }
  if (query.isError) {
    return <SearchRefusal error={query.error} />;
  }
  const pages = Math.max(1, Math.ceil(query.data.total / query.data.page_size));
  const choisi = query.data.objects.find((objet) => objet.cle === ouvert);
  return (
    <>
      <p className="caption" role="status">
        {t("storages.found", { count: query.data.total })}
      </p>
      {query.data.objects.length === 0 ? (
        // Vide n'est pas une erreur : ni un storage sans objet, ni un filtre qui ne
        // trouve rien. Le dire dans les mots du résultat, pas dans ceux d'une panne.
        <p className="help">{t("storages.empty")}</p>
      ) : (
        <div className="split">
          {/* Une région nommée, comme le journal des appels : la table et le panneau de
              détail sont deux zones de la page, et un lecteur d'écran doit pouvoir aller
              de l'une à l'autre. */}
          <section className="card-list split-list" aria-label={t("storages.table")}>
            {/* Le bandeau de colonnes, comme la maquette « Référentiel de comptes » le
                dessine : sans lui, les valeurs projetées ne se lisent pas comme des
                colonnes mais comme une suite de mots. */}
            <div className="row-head">
              <div className="cell-auto cell-key">{t("storages.columns.key")}</div>
              {storage.projections.map((projection) => (
                <div key={projection.column} className="cell-auto">
                  {projection.path}
                </div>
              ))}
              <div className="cell-auto">{t("storages.columns.seen")}</div>
            </div>
            <ul className="plain-list">
              {query.data.objects.map((objet) => (
                <li
                  key={objet.cle}
                  className={`row row-compact row-openable${
                    objet.cle === ouvert ? " row-selected" : ""
                  }`}
                >
                  <div className="cell-auto cell-key">
                    <button
                      type="button"
                      className="row-open mono"
                      aria-current={objet.cle === ouvert}
                      onClick={() => setOuvert(objet.cle)}
                    >
                      {/* La clé telle qu'on la lit : la forme canonique `["S-001"]` est
                          ce que la base compare, pas ce qu'un humain cherche. */}
                      {readableKey(objet.cle)}
                    </button>
                  </div>
                  {storage.projections.map((projection) => (
                    <div key={projection.column} className="cell-auto mono">
                      {String(objet.columns[projection.column] ?? "—")}
                    </div>
                  ))}
                  <div className="cell-auto caption">{instant(objet.vu_le)}</div>
                </li>
              ))}
            </ul>
          </section>
          {/* Dérivé de la page affichée : changer de page ou de filtre referme le
              panneau au lieu de décrire un objet absent de la table. */}
          <ObjectDetail objet={choisi} />
        </div>
      )}
      {pages > 1 && (
        <div className="actions">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
          >
            {t("storages.previous")}
          </button>
          <span className="caption">{t("storages.page", { page, pages })}</span>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={page >= pages}
            onClick={() => onPage(page + 1)}
          >
            {t("storages.next")}
          </button>
        </div>
      )}
    </>
  );
}
