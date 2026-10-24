import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type Storage,
  storageProblems,
  storageUsers,
  useDeleteStorage,
  useSaveStorage,
  useStorage,
} from "../api/storages";
import type { WorkTarget } from "../api/workTarget";
import { ConfirmDialog } from "../layout/ConfirmDialog";
import { StorageForm } from "./StorageForm";
import { storageErrorKey } from "./StoragesScreen";

function Editor({
  target,
  storage,
  onDeleted,
}: {
  target: WorkTarget;
  storage: Storage;
  onDeleted: () => void;
}) {
  const { t } = useTranslation();
  const save = useSaveStorage(target, storage.name);
  const remove = useDeleteStorage(target, storage.name);
  const [confirming, setConfirming] = useState(false);
  const problems = storageProblems(save.error);
  const users = storageUsers(remove.error);

  return (
    <>
      <StorageForm
        target={target}
        initial={storage}
        creating={false}
        problems={problems}
        pending={save.isPending}
        submitLabel={t("storages.editor.save")}
        onSubmit={(changed) => save.mutate(changed)}
      >
        <button type="button" className="btn btn-secondary" onClick={() => setConfirming(true)}>
          {t("storages.editor.delete")}
        </button>
      </StorageForm>
      {save.isSuccess && (
        <p className="muted" role="status">
          {/* Critère 13 : changer le modèle ou les indexables réécrit tout au prochain import. */}
          {t(save.data.rewrite_announced ? "storages.editor.savedRewrite" : "storages.editor.saved")}
        </p>
      )}
      {save.isError && problems.length === 0 && (
        <p className="alert" role="alert">
          {t(storageErrorKey(save.error))}
        </p>
      )}
      {/* Critère 14 : on nomme les sources qui le désignent, sinon le refus est opaque. */}
      {users.length > 0 && (
        <p className="alert" role="alert">
          {t("storages.errors.storage_utilise", { sources: users.join(", ") })}
        </p>
      )}
      {remove.isError && users.length === 0 && (
        <p className="alert" role="alert">
          {t("storages.errors.unexpected")}
        </p>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("storages.editor.deleteTitle")}
          confirmLabel={t("storages.editor.delete")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate(undefined, { onSuccess: onDeleted });
          }}
        >
          {t("storages.editor.deleteBody", { name: storage.name })}
        </ConfirmDialog>
      )}
    </>
  );
}

/** Un storage : sa déclaration, modifiable, et sa suppression. */
export function StorageScreen({
  target,
  name,
  onBack,
}: {
  target: WorkTarget;
  name: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const storage = useStorage(target, name);
  return (
    <section aria-labelledby="storage-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("storages.back")}
      </button>
      <h1 id="storage-title">
        {name} <span className="mono muted">storages/{name}.yaml</span>
      </h1>
      {storage.isPending && (
        <p className="muted" role="status">
          {t("dataModels.loading")}
        </p>
      )}
      {storage.isError && (
        <p className="alert" role="alert">
          {t("storages.errors.unreadable")}
        </p>
      )}
      {storage.data && (
        <Editor key={name} target={target} storage={storage.data} onDeleted={onBack} />
      )}
    </section>
  );
}
