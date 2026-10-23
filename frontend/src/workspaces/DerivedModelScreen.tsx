import { Suspense, lazy } from "react";
import { useTranslation } from "react-i18next";

import { type DerivedRef, useDerivedModel } from "../api/contracts";
import type { WorkTarget } from "../api/workTarget";
import { parseSchema } from "../dataModels/schemaText";
import { ContractRefusal } from "./ContractRefusal";

const SchemaEditor = lazy(() => import("../dataModels/SchemaEditor"));

/**
 * Un modèle dérivé d'un contrat (story 47f55d8b), dans l'éditeur des modèles mais en
 * lecture seule, quelle que soit la main : il dit ce que dit le contrat, il ne s'édite pas.
 */
export function DerivedModelScreen({
  target,
  derived,
  onBack,
}: {
  target: WorkTarget;
  derived: DerivedRef;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const model = useDerivedModel(target, derived);
  const data = model.data;
  const readOnly = { ...target, readOnly: true };

  return (
    <section aria-labelledby="derived-model-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("contractModels.back")}
      </button>
      {model.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {model.isError && <ContractRefusal error={model.error} />}
      {data && (
        <>
          <div className="page-head">
            <div>
              <h1 id="derived-model-title">{parsedTitle(data.content) ?? data.name}</h1>
              <p className="lead">
                <span className="mono">{data.path}</span> ·{" "}
                {t("contractModels.derivedFrom", { slug: derived.slug, version: derived.version })}
              </p>
            </div>
          </div>
          <p className="notice">{t("contractModels.readOnly")}</p>
          <div className="card" role="group" aria-label={t("dataModels.editor.title")}>
            <Suspense fallback={<p className="muted">{t("dataModels.loading")}</p>}>
              <SchemaEditor
                target={readOnly}
                model={{
                  scope: `contracts/${derived.slug}/v${derived.version}`,
                  name: data.name,
                  path: data.path,
                  label: null,
                  version: null,
                  content: data.content,
                }}
                models={[]}
                text={data.content}
                parsed={parseSchema(data.content)}
                onVisual={() => undefined}
                onYaml={() => undefined}
              />
            </Suspense>
          </div>
        </>
      )}
    </section>
  );
}

function parsedTitle(content: string): string | null {
  const parsed = parseSchema(content);
  const title = parsed.ok ? (parsed.schema as { title?: unknown }).title : null;
  return typeof title === "string" ? title : null;
}
