import { useQueryClient } from "@tanstack/react-query";
import { type JsonSchema, SchemaFieldsEditor, en, fr } from "jsonjoy-builder";
import "jsonjoy-builder/styles.css";
import { lazy, Suspense, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { parse } from "yaml";

import { type DataModel, type DataModelContent, SHARED_SCOPE, modelQuery } from "../api/dataModels";
import type { WorkTarget } from "../api/workTarget";
import { CopyButton } from "../layout/CopyButton";
import { type Parsed, modelUri, targetOf } from "./schemaText";

// Monaco ne se charge qu'à l'ouverture de cet écran (story e38806f3).
const YamlEditor = lazy(async () => {
  await import("./monaco");
  return import("./YamlEditor");
});

function visibleModels(models: DataModel[], model: DataModelContent): DataModel[] {
  // Même règle que le serveur : un modèle de domaine voit son domaine et les transverses ;
  // un transverse, les seuls transverses.
  return models.filter(
    (m) =>
      m.path !== model.path &&
      (m.scope === SHARED_SCOPE || (model.scope !== SHARED_SCOPE && m.scope === model.scope)),
  );
}

/**
 * L'éditeur visuel JSONJoy à gauche, le YAML dans Monaco à droite (story e38806f3), sur
 * le même schéma en mémoire. Le parent tient le texte et sa lecture ; rien n'est écrit ici.
 */
export default function SchemaEditor({
  target,
  model,
  models,
  text,
  parsed,
  onVisual,
  onYaml,
}: {
  target: WorkTarget;
  model: DataModelContent;
  models: DataModel[];
  text: string;
  parsed: Parsed;
  onVisual: (schema: JsonSchema) => void;
  onYaml: (text: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const client = useQueryClient();
  // Aperçu des modèles désignés par `$ref: miles:/…` : relus par la même requête que
  // l'écran, donc sous la même branche et le même cache.
  const resolve = useCallback(
    async (uri: string): Promise<JsonSchema> => {
      const found = targetOf(uri);
      if (found === null) throw new Error(t("dataModels.schema.externalRef", { uri }));
      const read = await client.fetchQuery(modelQuery(target, { scope: found[0], name: found[1] }));
      return parse(read.content) as JsonSchema;
    },
    [client, target, t],
  );
  const references = visibleModels(models, model);

  return (
    <div className="model-editor">
      <section aria-label={t("dataModels.schema.visual")}>
        <h2>{t("dataModels.schema.visual")}</h2>
        {parsed.ok ? (
          <SchemaFieldsEditor
            value={parsed.schema}
            onChange={onVisual}
            readOnly={target.readOnly}
            locale={i18n.language.startsWith("fr") ? fr : en}
            messages={{ refTargetPlaceholder: "miles:/shared/<nom> ou #/$defs/<nom>" }}
            resolveExternalRef={resolve}
          />
        ) : (
          <p className="notice" role="note">
            {t("dataModels.schema.unreadable", { message: parsed.message })}
          </p>
        )}
        {references.length > 0 && (
          <details className="panel">
            <summary>{t("dataModels.schema.references")}</summary>
            <p className="help">{t("dataModels.schema.referencesHelp")}</p>
            <ul className="plain-list">
              {references.map((m) => (
                <li key={m.path} className="field-row">
                  <span className="mono">{modelUri(m.scope, m.name)}</span>
                  <span className="muted">{m.label ?? m.name}</span>
                  <CopyButton text={modelUri(m.scope, m.name)} label={t("dataModels.schema.copy")} />
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
      <section aria-label={t("dataModels.fields.content")}>
        <h2>{t("dataModels.fields.content")}</h2>
        <Suspense fallback={<p className="muted">{t("dataModels.loading")}</p>}>
          <YamlEditor path={model.path} value={text} onChange={onYaml} readOnly={target.readOnly} />
        </Suspense>
      </section>
    </div>
  );
}
