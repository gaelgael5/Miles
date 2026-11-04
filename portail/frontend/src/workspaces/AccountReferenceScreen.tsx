import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import {
  type AccountReference,
  type Delivery,
  deliveryRefusal,
  unknownStorages,
  useAccountReference,
  useRemoveAccountReference,
  useSetAccountReference,
} from "../api/accounts";
import { useStorages } from "../api/storages";
import { AccountDelivery } from "./AccountDelivery";
import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";

/** Ce que le dépôt reproche au réglage, dit en toutes lettres plutôt qu'en code. */
function Problem({ reference }: { reference: AccountReference }) {
  const { t } = useTranslation();
  const problem = reference.problem;
  if (problem === null) {
    return null;
  }
  return (
    <p className="alert" role="alert">
      {t(`accounts.problems.${problem.code}`, {
        path: problem.path,
        storage: problem.detail ?? "",
        defaultValue: t("accounts.problems.unexpected", { path: problem.path }),
      })}
    </p>
  );
}

/**
 * La référence de compte de la branche (story a3ece1e9) : le storage dont les objets
 * sont les comptes qu'on associera aux devices.
 *
 * UNE liste déroulante, et rien d'autre — correction de Gael du 31/10/2026. Le modèle
 * n'est pas choisi : le storage le déclare déjà, et l'écran l'affiche. Faire choisir les
 * deux ferait saisir deux fois la même chose, et laisserait désigner un couple incohérent.
 *
 * L'écran est dans les vues de la BRANCHE et non dans « Paramétrage du workspace » : le
 * réglage désigne un objet de la branche, et il est versionné avec elle.
 */
export function AccountReferenceScreen({
  workspace,
  target,
  onBack,
}: {
  workspace: Workspace;
  target: WorkTarget;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const reference = useAccountReference(target);
  const storages = useStorages(target);
  const save = useSetAccountReference(target);
  const remove = useRemoveAccountReference(target);
  const [confirming, setConfirming] = useState(false);
  // Semé au rendu depuis la réponse, jamais recopié dans un effet : une réponse tardive
  // écraserait sinon un choix en cours de saisie.
  const [picked, setPicked] = useState<string | null>(null);
  const [delivery, setDelivery] = useState<Delivery | null | undefined>(undefined);
  const current = reference.data?.storage ?? "";
  const chosen = picked ?? current;
  // `undefined` veut dire « rien touché » : on rend alors ce que le serveur a lu. Un
  // `null` explicite, lui, est un retrait voulu de l'envoi.
  const sending = delivery === undefined ? (reference.data?.delivery ?? null) : delivery;
  const known = unknownStorages(save.error);
  const refused = deliveryRefusal(save.error);
  // Le modèle du stockage CHOISI, et non celui du réglage enregistré : tant que la
  // personne n'a pas validé, les champs proposés doivent suivre sa sélection en cours.
  const storage = storages.data?.find((s) => s.name === chosen);
  const model = chosen === current ? (reference.data?.model ?? null) : (storage?.model ?? null);

  return (
    <section aria-labelledby="account-reference-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="account-reference-title">
            {t("accounts.title", { name: workspace.name })}
          </h1>
          <p className="lead">{t("accounts.intro")}</p>
        </div>
      </div>
      {/* Dit une fois, en haut : rien n'interroge encore ce storage et aucun code ne part.
          Sans cette phrase, l'écran laisse croire que le dispositif fonctionne. */}
      <p className="notice">{t("accounts.notServed")}</p>

      {(reference.isPending || storages.isPending) && (
        <p className="muted" role="status">
          {t("dataModels.loading")}
        </p>
      )}
      {reference.isError && (
        <p className="alert" role="alert">
          {t("accounts.errors.unexpected")}
        </p>
      )}
      {reference.isSuccess && <Problem reference={reference.data} />}

      {storages.isSuccess && storages.data.length === 0 && (
        // Une liste vide sans explication laisserait chercher ce qui ne va pas : c'est
        // qu'il n'y a aucun storage à désigner, et il faut en déclarer un d'abord.
        <p className="alert">{t("accounts.noStorage")}</p>
      )}

      {reference.isSuccess && storages.isSuccess && storages.data.length > 0 && (
        <form
          className="card"
          aria-label={t("accounts.title", { name: workspace.name })}
          onSubmit={(event) => {
            event.preventDefault();
            if (chosen !== "") {
              save.mutate({ storage: chosen, delivery: sending });
            }
          }}
        >
          <label>
            {t("accounts.fields.storage")}
            <select
              value={chosen}
              disabled={target.readOnly}
              onChange={(event) => {
                setPicked(event.target.value);
                // Changer de stockage change le modèle, donc les champs proposés :
                // garder l'ancien champ d'adresse le ferait pointer dans le vide.
                setDelivery(null);
              }}
            >
              <option value="">{t("accounts.choose")}</option>
              {storages.data.map((s) => (
                <option key={s.name} value={s.name}>
                  {s.label ?? s.name}
                </option>
              ))}
            </select>
          </label>
          <p className="help">{t("accounts.storageHelp")}</p>

          <div className="cell">
            <div className="caption">{t("accounts.fields.model")}</div>
            {/* Lu dans le storage, jamais saisi : c'est pourquoi il est rendu ici comme
                une valeur et non comme un champ. */}
            <div className="value mono">{model ?? t("accounts.noModel")}</div>
          </div>

          <AccountDelivery
            target={target}
            model={model}
            modes={reference.data.modes}
            served={reference.data.served_modes}
            value={sending}
            readOnly={target.readOnly}
            onChange={setDelivery}
          />

          {reference.data.storage === null && <p className="muted">{t("accounts.none")}</p>}

          {!target.readOnly && (
            <div className="actions">
              <button
                type="submit"
                className="btn btn-primary"
                disabled={save.isPending || chosen === ""}
              >
                {t("accounts.save")}
              </button>
              {reference.data.storage !== null && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setConfirming(true)}
                >
                  {t("accounts.remove")}
                </button>
              )}
            </div>
          )}
          {save.isSuccess && (
            <p className="notice" role="status">
              {t("accounts.saved")}
            </p>
          )}
          {save.isError && known.length > 0 && (
            <p className="alert" role="alert">
              {t("accounts.errors.storage_inconnu", { existants: known.join(", ") })}
            </p>
          )}
          {refused !== null && (
            <p className="alert" role="alert">
              {t(`accounts.errors.${refused.code}`, {
                detail: refused.detail ?? "",
                servis: refused.servis.map((m) => t(`accounts.modes.${m}`)).join(", "),
                defaultValue: t("accounts.errors.unexpected"),
              })}
            </p>
          )}
          {save.isError && known.length === 0 && refused === null && (
            <p className="alert" role="alert">
              {t("accounts.errors.unexpected")}
            </p>
          )}
        </form>
      )}

      {confirming && (
        <ConfirmDialog
          title={t("accounts.removeTitle")}
          confirmLabel={t("accounts.remove")}
          cancelLabel={t("dataModels.form.cancel")}
          onConfirm={() => {
            remove.mutate(undefined, {
              onSuccess: () => {
                setPicked(null);
                setDelivery(undefined);
              },
            });
            setConfirming(false);
          }}
          onCancel={() => setConfirming(false)}
        >
          <p>{t("accounts.removeBody")}</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
