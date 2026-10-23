import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type DataModel,
  type DataModelContent,
  SHARED_SCOPE,
  useDataModel,
  useDataModels,
  useReplaceDataModel,
} from "../api/dataModels";
import type { WorkTarget } from "../api/workTarget";
import { ModelTree } from "../dataModels/ModelTree";
import { type ModelDoc, parseModel, serializeModel } from "../dataModels/modelTree";
import { ConfirmDialog } from "../layout/ConfirmDialog";
import { ModelRefusal } from "./ModelRefusal";

function visibleModels(models: DataModel[] | undefined, scope: string, own: string): string[] {
  // Même règle que le serveur : un modèle de domaine voit son domaine et les transverses ;
  // un transverse, les seuls transverses. Lui-même reste désignable.
  const visible = (models ?? []).filter((m) => m.scope === SHARED_SCOPE || m.scope === scope);
  return [...new Set([own, ...visible.map((m) => m.name)])].sort();
}

/**
 * Arbre à gauche, YAML à droite (story 7208ba06), synchronisés et en mémoire seulement :
 * rien ne part au serveur avant « Enregistrer ».
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
  const [state, setState] = useState(() => parseModel(model.content));
  const dirty = text !== model.content;

  function fromTree(doc: ModelDoc) {
    // L'arbre fait foi : le YAML est réécrit, sans repasser par la lecture qui
    // renouvellerait les identifiants et ferait perdre le champ en cours de saisie.
    const next = serializeModel(doc);
    setText(next);
    setState({ ok: true, doc });
    onDirty(next !== model.content);
  }

  function fromYaml(next: string) {
    setText(next);
    setState(parseModel(next));
    onDirty(next !== model.content);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    replace.mutate(text, {
      onSuccess: () => {
        onDirty(false);
        onSaved();
      },
    });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("dataModels.editor.title")}>
      <div className="model-editor">
        <section aria-label={t("dataModels.tree.title")}>
          <h2>{t("dataModels.tree.title")}</h2>
          {state.ok ? (
            <ModelTree
              doc={state.doc}
              onChange={fromTree}
              models={visibleModels(models.data, model.scope, model.name)}
              readOnly={target.readOnly}
            />
          ) : (
            <p className="notice" role="note">
              {state.reason === "syntax"
                ? t("dataModels.tree.unreadable", {
                    line: state.line ?? "?",
                    column: state.column ?? "?",
                    message: state.message,
                  })
                : t("dataModels.tree.unsupported", { path: state.path })}
            </p>
          )}
        </section>
        <label className="field">
          {t("dataModels.fields.content")}
          <textarea
            rows={24}
            className="mono"
            spellCheck={false}
            readOnly={target.readOnly}
            value={text}
            onChange={(e) => fromYaml(e.target.value)}
          />
        </label>
      </div>
      <p className="help">{t("dataModels.editor.help")}</p>
      {replace.isError && <ModelRefusal error={replace.error} />}
      {!target.readOnly && (
        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={replace.isPending || !dirty}>
            {t("dataModels.editor.save")}
          </button>
          {dirty && <span className="badge badge-warning">{t("dataModels.editor.unsaved")}</span>}
        </div>
      )}
    </form>
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
                {scope === SHARED_SCOPE ? t("dataModels.list.shared") : scope}
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
