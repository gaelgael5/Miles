import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type Source, sourceProblems, useDeleteSource, useSaveSource, useSource } from "../api/sources";
import type { WorkTarget } from "../api/workTarget";
import { ConfirmDialog } from "../layout/ConfirmDialog";
import { SourceForm } from "./SourceForm";
import { sourceErrorKey } from "./SourcesScreen";

function Editor({
  target,
  source,
  onDeleted,
  onSwagger,
}: {
  target: WorkTarget;
  source: Source;
  onDeleted: () => void;
  onSwagger: () => void;
}) {
  const { t } = useTranslation();
  const save = useSaveSource(target, source.name);
  const remove = useDeleteSource(target, source.name);
  const [confirming, setConfirming] = useState(false);
  const problems = sourceProblems(save.error);

  return (
    <>
      <SourceForm
        target={target}
        initial={source}
        creating={false}
        problems={problems}
        pending={save.isPending}
        submitLabel={t("sources.editor.save")}
        onSubmit={(changed) => save.mutate(changed)}
      >
        {/* L'API que cette source promet, lue dans le même visualiseur que les
            contrats (Gael, 25/10/2026) : elle est dérivée de la déclaration. */}
        <button type="button" className="btn btn-secondary" onClick={onSwagger}>
          {t("sources.editor.swagger")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => setConfirming(true)}>
          {t("sources.editor.delete")}
        </button>
      </SourceForm>
      {save.isSuccess && (
        <p className="muted" role="status">
          {/* Critère 17 : changer la chaîne réécrit tout au prochain import. */}
          {t(save.data.rewrite_announced ? "sources.editor.savedRewrite" : "sources.editor.saved")}
        </p>
      )}
      {save.isError && problems.length === 0 && (
        <p className="alert" role="alert">{t(sourceErrorKey(save.error))}</p>
      )}
      {remove.isError && <p className="alert" role="alert">{t("sources.errors.unexpected")}</p>}
      {confirming && (
        <ConfirmDialog
          title={t("sources.editor.deleteTitle")}
          confirmLabel={t("sources.editor.delete")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate(undefined, { onSuccess: onDeleted });
          }}
        >
          {t("sources.editor.deleteBody", { name: source.name })}
        </ConfirmDialog>
      )}
    </>
  );
}

/** Une source de données : sa déclaration, modifiable, et sa suppression. */
export function SourceScreen({
  target,
  name,
  onBack,
  onSwagger,
}: {
  target: WorkTarget;
  name: string;
  onBack: () => void;
  /** Lire l'API que cette source promet (Gael, 25/10/2026). */
  onSwagger: () => void;
}) {
  const { t } = useTranslation();
  const source = useSource(target, name);
  return (
    <section aria-labelledby="source-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("sources.back")}
      </button>
      <h1 id="source-title">
        {name} <span className="mono muted">sources/{name}.yaml</span>
      </h1>
      {source.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {source.isError && <p className="alert" role="alert">{t("sources.errors.unreadable")}</p>}
      {source.data && (
        <Editor
          key={name}
          target={target}
          source={source.data}
          onDeleted={onBack}
          onSwagger={onSwagger}
        />
      )}
    </section>
  );
}
