import { type ChangeEvent, Suspense, lazy, useState } from "react";
import { useTranslation } from "react-i18next";

import { type SampleFormat, useInferSchema } from "../api/dataModels";
import { ApiError } from "../api/http";
import type { WorkTarget } from "../api/workTarget";

const SampleEditor = lazy(() => import("./YamlEditor"));

const FORMATS: SampleFormat[] = ["json", "yaml"];

/** Le refus propre à l'import nomme l'endroit où l'échantillon casse. */
function refusal(error: unknown): { key: string; line?: number; column?: number } {
  if (error instanceof ApiError && error.status === 422) {
    const detail = error.detail as
      | { code?: string; line?: number | null; column?: number | null }
      | undefined;
    if (detail?.code === "echantillon_illisible") {
      return {
        key: "dataModels.import.unreadable",
        line: detail.line ?? undefined,
        column: detail.column ?? undefined,
      };
    }
    if (detail?.code === "echantillon_sans_objet") {
      return { key: "dataModels.import.noObject" };
    }
  }
  return { key: "dataModels.import.failed" };
}

/**
 * Import intelligent (Gael, 24/10/2026) : on colle un échantillon, Miles en déduit la
 * forme du modèle. La déduction est faite par le serveur — c'est la même règle pour
 * l'écran et pour la surface MCP.
 *
 * Proposé sur un modèle encore vide seulement : sur un modèle déjà décrit, il écraserait
 * un travail sans le dire.
 */
export function ImportSmart({
  target,
  path,
  onImported,
  onCancel,
}: {
  target: WorkTarget;
  // Désigne le document dans Monaco ; l'échantillon n'est pas un schéma, donc aucun
  // méta-schéma ne s'y rattache.
  path: string;
  onImported: (schema: Record<string, unknown>, unwrapped: boolean) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [format, setFormat] = useState<SampleFormat>("json");
  const [sample, setSample] = useState("");
  const infer = useInferSchema(target);
  const problem = infer.isError ? refusal(infer.error) : null;

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    // Lu dans le navigateur : le fichier ne part au serveur que comme texte, par la
    // même route que ce qu'on colle. Un seul chemin à éprouver côté serveur.
    void file.text().then(setSample);
  }

  return (
    <div className="overlay" onClick={onCancel}>
      <div
        className="dialog dialog-wide"
        role="dialog"
        aria-modal="true"
        aria-label={t("dataModels.import.title")}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            onCancel();
          }
        }}
      >
        <div className="card">
        <h2>{t("dataModels.import.title")}</h2>
        <p className="help">{t("dataModels.import.explain")}</p>
        <div className="actions" role="group" aria-label={t("dataModels.import.format")}>
          {FORMATS.map((value) => (
            <button
              key={value}
              type="button"
              className={`btn ${format === value ? "btn-primary" : "btn-secondary"}`}
              aria-pressed={format === value}
              onClick={() => setFormat(value)}
            >
              {t(`dataModels.import.formats.${value}`)}
            </button>
          ))}
        </div>
        <label className="field">
          {t("dataModels.import.file")}
          <input type="file" accept=".json,.yaml,.yml,application/json,text/yaml" onChange={chooseFile} />
        </label>
        <Suspense fallback={<p className="muted">{t("dataModels.loading")}</p>}>
          <SampleEditor
            path={`${path}.sample.${format}`}
            value={sample}
            onChange={setSample}
            readOnly={false}
            language={format}
            height="320px"
            attachMetaSchema={false}
            ariaLabel={t("dataModels.import.sample")}
          />
        </Suspense>
        {problem && (
          <p className="alert" role="alert">
            {t(problem.key, { line: problem.line, column: problem.column })}
          </p>
        )}
        <div className="actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={sample.trim() === "" || infer.isPending}
            onClick={() =>
              infer.mutate({ format, sample }, {
                onSuccess: (got) => onImported(got.schema, got.unwrapped),
              })
            }
          >
            {t("dataModels.import.submit")}
          </button>
          <button type="button" className="btn btn-secondary" onClick={onCancel}>
            {t("dataModels.import.cancel")}
          </button>
        </div>
        </div>
      </div>
    </div>
  );
}
