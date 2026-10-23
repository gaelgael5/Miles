import type { JsonSchema } from "jsonjoy-builder";
import { Suspense, lazy, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type DataModelContent,
  SHARED_SCOPE,
  useDataModel,
  useDataModels,
  useReplaceDataModel,
} from "../api/dataModels";
import type { WorkTarget } from "../api/workTarget";
import { parseSchema, sameSchema, schemaText } from "../dataModels/schemaText";
import { ConfirmDialog } from "../layout/ConfirmDialog";
import { ModelRefusal } from "./ModelRefusal";

// JSONJoy et Monaco ne se chargent qu'à l'ouverture d'un modèle : le reste du portail ne
// paie pas leur poids (story e38806f3).
const SchemaEditor = lazy(() => import("../dataModels/SchemaEditor"));

/**
 * Éditeur visuel à gauche, YAML à droite (story e38806f3), synchronisés et en mémoire
 * seulement : rien ne part au serveur avant « Enregistrer », qui reste l'arbitre.
 */
function Editor({
  target,
  model,
  onDirty,
  onSaved,
}: {
  target: WorkTarget;
  model: DataModelContent;
  onDirty: (dirty: boolean) => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const replace = useReplaceDataModel(target, model);
  const models = useDataModels(target);
  const [text, setText] = useState(model.content);
  const [parsed, setParsed] = useState(() => parseSchema(model.content));
  const dirty = !sameSchema(text, model.content);

  function changed(next: string) {
    onDirty(!sameSchema(next, model.content));
  }

  function fromVisual(schema: JsonSchema) {
    // L'éditeur visuel fait foi : le YAML est réécrit, sans le relire.
    const next = schemaText(schema);
    setText(next);
    setParsed({ ok: true, schema });
    changed(next);
  }

  function fromYaml(next: string) {
    setText(next);
    setParsed(parseSchema(next));
    changed(next);
  }

  function save() {
    replace.mutate(text, {
      onSuccess: () => {
        onDirty(false);
        onSaved();
      },
    });
  }

  return (
    // Pas de <form> ici, exprès : JSONJoy porte ses propres formulaires (ajout d'une
    // définition) ; imbriqués dans le nôtre, leur envoi rechargeait toute la page.
    <div className="card" role="group" aria-label={t("dataModels.editor.title")}>
      <Suspense fallback={<p className="muted">{t("dataModels.loading")}</p>}>
        <SchemaEditor
          target={target}
          model={model}
          models={models.data ?? []}
          text={text}
          parsed={parsed}
          onVisual={fromVisual}
          onYaml={fromYaml}
        />
      </Suspense>
      <p className="help">{t("dataModels.editor.help")}</p>
      {replace.isError && <ModelRefusal error={replace.error} />}
      {!target.readOnly && (
        <div className="actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={replace.isPending || !dirty}
            onClick={save}
          >
            {t("dataModels.editor.save")}
          </button>
          {dirty && <span className="badge badge-warning">{t("dataModels.editor.unsaved")}</span>}
        </div>
      )}
    </div>
  );
}

/**
 * Édition d'un modèle (Gael, 23/10/2026) : c'est ici que s'écrit son YAML. Sans la main,
 * ou sur la racine, il se lit sans se modifier.
 */
export function DataModelScreen({
  target,
  scope,
  name,
  onBack,
}: {
  target: WorkTarget;
  scope: string;
  name: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const model = useDataModel(target, { scope, name });
  const data = model.data;
  const [dirty, setDirty] = useState(false);
  const [leaving, setLeaving] = useState(false);
  // Tenu ici : l'éditeur est remonté sur le contenu relu après l'enregistrement.
  const [saved, setSaved] = useState(false);

  return (
    <section aria-labelledby="data-model-title">
      {/* Le travail n'est qu'en mémoire : on ne le perd pas d'un clic sans l'avoir vu. */}
      <button
        type="button"
        className="btn btn-secondary back"
        onClick={() => (dirty ? setLeaving(true) : onBack())}
      >
        {t("dataModels.editor.back")}
      </button>
      {leaving && (
        <ConfirmDialog
          title={t("dataModels.editor.leaveTitle")}
          confirmLabel={t("dataModels.editor.leave")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setLeaving(false)}
          onConfirm={onBack}
        >
          <p>{t("dataModels.editor.leaveBody")}</p>
        </ConfirmDialog>
      )}
      {model.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {model.isError && <ModelRefusal error={model.error} />}
      {data && (
        <>
          <div className="page-head">
            <div>
              <h1 id="data-model-title">{data.label ?? data.name}</h1>
              <p className="lead">
                <span className="mono">{data.path}</span> ·{" "}
                {scope === SHARED_SCOPE ? t("dataModels.list.shared") : scope} ·{" "}
                {/* Tenue par le système (0f7cda10) : affichée, jamais saisie. */}
                <span title={t("dataModels.schema.versionHelp")}>
                  {t("dataModels.schema.version", { version: data.version ?? "—" })}
                </span>
              </p>
            </div>
          </div>
          {/* Clé de contenu : une relecture après enregistrement repart du texte du dépôt. */}
          {saved && !dirty && (
            <p className="notice" role="status">
              {t("dataModels.editor.saved")}
            </p>
          )}
          <Editor
            key={data.content}
            target={target}
            model={data}
            onDirty={(value) => {
              setDirty(value);
              if (value) setSaved(false);
            }}
            onSaved={() => setSaved(true)}
          />
        </>
      )}
    </section>
  );
}
