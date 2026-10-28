import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog, PageHead } from "@miles/socle-web";

import {
  type Environment,
  refusKey,
  useCreateEnvironment,
  useDeleteEnvironment,
  useEnvironments,
  useRenameEnvironment,
} from "../api/environments";
import { EnvironmentForm } from "./EnvironmentForm";

function EnvironmentRow({
  environnement,
  onRename,
}: {
  environnement: Environment;
  onRename: () => void;
}) {
  const { t } = useTranslation();
  const [confirme, setConfirme] = useState(false);
  const suppression = useDeleteEnvironment();
  const apparie = environnement.paired_base_url !== null;

  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{environnement.label}</div>
        <div className="row-sub">{environnement.slug}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("environments.list.captionPairing")}</div>
        <div className="value">
          {apparie ? (
            <span className="badge badge-success">{t("environments.list.paired")}</span>
          ) : (
            // Pas de pastille d'alerte : un environnement déclaré et pas encore apparié
            // est l'état du premier jour, pas un défaut à corriger.
            <span className="muted">{t("environments.list.notPaired")}</span>
          )}
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("environments.list.captionStack")}</div>
        <div className="value">{environnement.paired_base_url ?? "—"}</div>
      </div>
      <div className="actions row-actions">
        <button type="button" className="btn btn-secondary" onClick={onRename}>
          {t("environments.actions.rename")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => setConfirme(true)}>
          {t("environments.actions.delete")}
        </button>
      </div>
      {suppression.isError && (
        <p className="alert alert-danger" role="alert">
          {t(refusKey(suppression.error))}
        </p>
      )}
      {confirme && (
        <ConfirmDialog
          title={t("environments.delete.title")}
          confirmLabel={t("environments.delete.confirm")}
          cancelLabel={t("environments.delete.cancel")}
          onCancel={() => setConfirme(false)}
          onConfirm={() => {
            setConfirme(false);
            suppression.mutate(environnement.id);
          }}
        >
          {/* La confirmation NOMME ce qui va disparaître : une liste de slugs proches se
              confond, et le dialogue est le dernier endroit où l'erreur se rattrape. */}
          <p>{t("environments.delete.body", { label: environnement.label })}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

export function EnvironmentsScreen() {
  const { t } = useTranslation();
  const environnements = useEnvironments();
  const creation = useCreateEnvironment();
  const renommage = useRenameEnvironment();
  const [renomme, setRenomme] = useState<Environment | null>(null);
  // Compte les créations réussies, et sert de clef au formulaire pour le remonter vide.
  // Compté ici plutôt que lu de `dataUpdatedAt` : la liste se relit aussi après un
  // renommage ou une suppression, et le formulaire effacerait alors une saisie en cours.
  const [creations, setCreations] = useState(0);

  return (
    <section className="section" aria-labelledby="environments-title">
      <PageHead
        id="environments-title"
        title={t("environments.title")}
        lead={t("environments.lead")}
      />
      <div className="card">
        <div className="card-head">
          <h2>
            {renomme === null
              ? t("environments.form.createTitle")
              : t("environments.form.renameTitle", { label: renomme.label })}
          </h2>
        </div>
        {renomme === null ? (
          <EnvironmentForm
            // La clef remonte le formulaire après chaque création réussie : sans elle,
            // le libellé et le slug du précédent resteraient affichés et le suivant
            // partirait d'une saisie qui n'est plus la sienne.
            key={`creation-${creations}`}
            label=""
            slug=""
            submitLabel={t("environments.form.submitCreate")}
            pending={creation.isPending}
            error={creation.isError ? creation.error : null}
            onSubmit={(input) =>
              creation.mutate(input, { onSuccess: () => setCreations((n) => n + 1) })
            }
          />
        ) : (
          <EnvironmentForm
            key={renomme.id}
            label={renomme.label}
            slug={renomme.slug}
            submitLabel={t("environments.form.submitRename")}
            pending={renommage.isPending}
            error={renommage.isError ? renommage.error : null}
            onSubmit={(input) =>
              renommage.mutate({ id: renomme.id, ...input }, { onSuccess: () => setRenomme(null) })
            }
            onCancel={() => setRenomme(null)}
          />
        )}
      </div>
      <div className="card">
        <div className="card-head">
          <h2>{t("environments.list.title")}</h2>
        </div>
        {environnements.isPending && <p role="status">{t("environments.loading")}</p>}
        {environnements.isError && (
          <p className="alert alert-danger" role="alert">
            {t("environments.error")}
          </p>
        )}
        {environnements.data?.length === 0 && (
          <p role="status">{t("environments.list.empty")}</p>
        )}
        <ul className="plain-list">
          {(environnements.data ?? []).map((environnement) => (
            <EnvironmentRow
              key={environnement.id}
              environnement={environnement}
              onRename={() => setRenomme(environnement)}
            />
          ))}
        </ul>
      </div>
    </section>
  );
}
