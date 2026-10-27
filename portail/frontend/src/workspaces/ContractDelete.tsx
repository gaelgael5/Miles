import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import { useDeleteContract } from "../api/contracts";
import type { WorkTarget } from "../api/workTarget";
import { ContractRefusal } from "./ContractRefusal";

/**
 * Supprimer un contrat avec toutes ses versions (ticket 6e15d4cd), après confirmation.
 * Jamais une version seule : le contrat est importé, pas édité.
 */
export function ContractDelete({
  target,
  slug,
  versions,
  onDeleted,
}: {
  target: WorkTarget;
  slug: string;
  versions: number;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  const remove = useDeleteContract(target, slug);
  const [confirming, setConfirming] = useState(false);
  return (
    <>
      <button
        type="button"
        className="btn btn-danger"
        disabled={remove.isPending}
        onClick={() => setConfirming(true)}
      >
        {t("contracts.delete.action")}
      </button>
      {remove.isError && <ContractRefusal error={remove.error} />}
      {confirming && (
        <ConfirmDialog
          title={t("contracts.delete.title", { slug })}
          confirmLabel={t("contracts.delete.action")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate(undefined, { onSuccess: onDeleted });
          }}
        >
          <p>{t("contracts.delete.body", { count: versions })}</p>
        </ConfirmDialog>
      )}
    </>
  );
}
