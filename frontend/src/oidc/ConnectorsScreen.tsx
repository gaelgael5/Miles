import { useState } from "react";
import { useTranslation } from "react-i18next";

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
    <li>
      <strong>{connector.label}</strong> <code>{connector.id}</code> {connector.issuer}{" "}
      <span>{t(connector.active ? "oidc.list.active" : "oidc.list.inactive")}</span>{" "}
      <button type="button" onClick={onEdit}>
        {t("oidc.list.edit")}
      </button>
      <button type="button" onClick={() => remove.mutate(connector.id)}>
        {t("oidc.list.delete")}
      </button>
      {remove.isError && <p role="alert">{t(deleteErrorKey(remove.error))}</p>}
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
      <h2 id="oidc-title">{t("oidc.title")}</h2>
      <p>{t("oidc.intro")}</p>
      {editing === null ? (
        <button type="button" onClick={() => setEditing("new")}>
          {t("oidc.list.add")}
        </button>
      ) : (
        <ConnectorForm key={editing} connector={edited} onDone={() => setEditing(null)} />
      )}
      {connectors.isPending && <p role="status">{t("oidc.list.loading")}</p>}
      {connectors.isError && <p role="alert">{t("oidc.errors.unreachable")}</p>}
      {connectors.isSuccess && connectors.data.length === 0 && <p>{t("oidc.list.empty")}</p>}
      {connectors.isSuccess && connectors.data.length > 0 && (
        <ul>
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
