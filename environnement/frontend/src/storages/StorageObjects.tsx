import type { UseQueryResult } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { ApiError } from "@miles/socle-web";
import type { ObjectPage, Storage } from "../api/storages";

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
  const { t, i18n } = useTranslation();
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
        <ul className="plain-list">
          {query.data.objects.map((objet) => (
            <li key={objet.cle} className="row">
              <div className="row-main">
                <div className="row-title mono">{objet.cle}</div>
                <div className="row-sub">
                  {storage.projections.map((projection) => (
                    <span key={projection.column}>
                      {projection.path} :{" "}
                      <span className="mono">
                        {String(objet.columns[projection.column] ?? "—")}
                      </span>
                      {"  "}
                    </span>
                  ))}
                </div>
                <div className="row-sub caption">
                  {t("storages.seen", {
                    date: new Date(objet.vu_le).toLocaleString(i18n.language),
                  })}
                  {" · "}
                  {t("storages.changed", {
                    date: new Date(objet.modifie_le).toLocaleString(i18n.language),
                  })}
                  {" · "}
                  {t(`storages.origins.${objet.origine}`, { defaultValue: objet.origine })}
                </div>
              </div>
              <pre className="row-detail mono">{JSON.stringify(objet.objet, null, 2)}</pre>
            </li>
          ))}
        </ul>
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
