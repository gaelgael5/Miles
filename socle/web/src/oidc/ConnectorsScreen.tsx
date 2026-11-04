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

/**
 * Un connecteur dans la colonne de gauche : son libellé, son état, et rien d'autre.
 *
 * La maquette « Connecteurs OIDC » met la LISTE à gauche et le connecteur ouvert à droite.
 * Les gestes sont donc partis de la ligne : une colonne de 280px qui porterait deux
 * boutons par ligne ne se parcourt plus, et c'est ce qu'on venait y faire — voir lequel
 * est actif, et ouvrir celui qu'on cherche.
 */
function ConnectorPick({
  connector,
  current,
  onOpen,
}: {
  connector: Connector;
  current: boolean;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <li className={current ? "pick pick-now" : "pick"}>
      <button type="button" className="pick-open" onClick={onOpen} aria-current={current}>
        <span className="pick-title">{connector.label}</span>
        <span className="pick-sub">
          {t(connector.active ? "oidc.list.active" : "oidc.list.inactive")}
          {connector.recognize_admin && ` · ${t("oidc.list.recognizesAdmin")}`}
        </span>
      </button>
    </li>
  );
}

/** Connecteurs OIDC déclarés à la racine : chacun devient un bouton de l'écran de connexion. */
export function ConnectorsScreen() {
  const { t } = useTranslation();
  const connectors = useConnectors();
  const remove = useDeleteConnector();
  // null : rien d'ouvert ; "new" : création ; sinon l'identifiant du connecteur ouvert.
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
      {connectors.isPending && <p className="muted" role="status">{t("oidc.list.loading")}</p>}
      {connectors.isError && <p className="alert" role="alert">{t("oidc.errors.unreachable")}</p>}
      {connectors.isSuccess && connectors.data.length === 0 && editing === null && (
        <p>{t("oidc.list.empty")}</p>
      )}
      <div className="master-detail">
        {connectors.isSuccess && connectors.data.length > 0 && (
          <ul className="card-list plain-list pick-list">
            {connectors.data.map((connector) => (
              <ConnectorPick
                key={connector.id}
                connector={connector}
                current={connector.id === editing}
                onOpen={() => setEditing(connector.id)}
              />
            ))}
          </ul>
        )}
        <div className="detail">
          {editing !== null && (
            <ConnectorForm
              key={editing}
              connector={edited}
              others={(connectors.data ?? []).filter((c) => c.id !== editing)}
              onDone={() => setEditing(null)}
            />
          )}
          {/* La suppression est SOUS le connecteur ouvert, et non dans la liste : elle
              porte sur ce qu'on est en train de lire. Dans la liste, elle demandait de
              viser la bonne ligne pour un geste qui ne se rattrape pas. */}
          {edited !== undefined && (
            // Dans un panneau, et non posée nue sous la carte : seule au bas de l'écran,
            // elle flottait sans rien dire de ce sur quoi elle porte.
            <div className="panel">
              <div className="actions row-actions">
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={() => remove.mutate(edited.id, { onSuccess: () => setEditing(null) })}
                  disabled={remove.isPending}
                >
                  {t("oidc.list.delete")}
                </button>
              </div>
              {remove.isError && (
                <p className="alert" role="alert">{t(deleteErrorKey(remove.error))}</p>
              )}
            </div>
          )}
          {editing === null && connectors.isSuccess && connectors.data.length > 0 && (
            <p className="help">{t("oidc.list.pick")}</p>
          )}
        </div>
      </div>
    </section>
  );
}
