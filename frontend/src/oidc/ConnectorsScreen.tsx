import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PageHead } from "../layout/PageHead";
import { ApiError } from "../api/http";
import { type Connector, useConnectors, useDeleteConnector } from "../api/oidc";
import { ConnectorForm } from "./ConnectorForm";

function deleteErrorKey(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return "oidc.errors.inUse";
  }
  return "oidc.errors.unexpected";
}

function ConnectorRow({ connector, onEdit }: { connector: Connector; onEdit: () => void }) {
  const { t } = useTranslation();
  const remove = useDeleteConnector();
  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{connector.label}</div>
        <div className="row-sub">
          {connector.id} · {connector.issuer}
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("oidc.list.captionState")}</div>
        <div className="value">
          <span className={connector.active ? "badge badge-success" : "badge"}>
            {t(connector.active ? "oidc.list.active" : "oidc.list.inactive")}
          </span>{" "}
          {connector.recognize_admin && (
            <span className="badge badge-accent">{t("oidc.list.recognizesAdmin")}</span>
          )}
        </div>
      </div>
      <div className="actions row-actions">
        <button type="button" className="btn btn-secondary" onClick={onEdit}>
          {t("oidc.list.edit")}
        </button>
        <button type="button" className="btn btn-danger" onClick={() => remove.mutate(connector.id)}>
          {t("oidc.list.delete")}
        </button>
      </div>
      {remove.isError && (
        <p className="alert row-detail" role="alert">{t(deleteErrorKey(remove.error))}</p>
      )}
    </li>
  );
}

/** Connecteurs OIDC déclarés à la racine : chacun devient un bouton de l'écran de connexion. */
export function ConnectorsScreen() {
  const { t } = useTranslation();
  const connectors = useConnectors();
  // null : liste ; "new" : création ; sinon l'identifiant du connecteur modifié.
  const [editing, setEditing] = useState<string | null>(null);
  const edited = connectors.data?.find((c) => c.id === editing);

  return (
    <section aria-labelledby="oidc-title">
      <PageHead
        id="oidc-title"
        title={t("oidc.title")}
        lead={t("oidc.intro")}
        action={
          editing === null && (
            <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}>
              {t("oidc.list.add")}
            </button>
          )
        }
      />
      {editing !== null && (
        <ConnectorForm
          key={editing}
          connector={edited}
          others={(connectors.data ?? []).filter((c) => c.id !== editing)}
          onDone={() => setEditing(null)}
        />
      )}
      {connectors.isPending && <p className="muted" role="status">{t("oidc.list.loading")}</p>}
      {connectors.isError && <p className="alert" role="alert">{t("oidc.errors.unreachable")}</p>}
      {connectors.isSuccess && connectors.data.length === 0 && <p>{t("oidc.list.empty")}</p>}
      {connectors.isSuccess && connectors.data.length > 0 && (
        <ul className="card-list plain-list">
          {connectors.data.map((connector) => (
            <ConnectorRow
              key={connector.id}
              connector={connector}
              onEdit={() => setEditing(connector.id)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
