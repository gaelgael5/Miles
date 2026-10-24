import { useTranslation } from "react-i18next";

import type { ChainStep, StepProblem } from "../api/chains";
import { type DataModel, useDataModels } from "../api/dataModels";
import type { WorkTarget } from "../api/workTarget";
import { modelUri } from "../dataModels/schemaText";

function moved(steps: ChainStep[], from: number, to: number): ChainStep[] {
  const next = [...steps];
  const [step] = next.splice(from, 1);
  if (step !== undefined) {
    next.splice(to, 0, step);
  }
  return next;
}

/** Ce qu'on montre d'un modèle choisi : son label, ou son nom à défaut. */
function labelOf(models: DataModel[], uri: string | null): string | null {
  if (uri === null) {
    return null;
  }
  const found = models.find((m) => modelUri(m.scope, m.name) === uri);
  return found ? (found.label ?? found.name) : uri;
}

function ModelPicker({
  caption,
  models,
  value,
  readOnly,
  onChange,
}: {
  caption: string;
  models: DataModel[];
  value: string | null;
  readOnly: boolean;
  onChange: (uri: string | null) => void;
}) {
  const { t } = useTranslation();
  return (
    <label className="field">
      {caption}
      <select
        disabled={readOnly}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">{t("chains.steps.noModel")}</option>
        {models.map((model) => (
          <option key={model.path} value={modelUri(model.scope, model.name)}>
            {model.label ?? model.name}
          </option>
        ))}
      </select>
    </label>
  );
}

/**
 * Étapes d'une chaîne, dans l'ordre d'application (Gael, 24/10/2026).
 *
 * Une étape est une LIGNE : ce qu'elle transforme, et rien de plus. Le template a quitté
 * cet écran — il s'édite en page pleine, où l'on travaille vraiment la transformation.
 * Les deux sélecteurs de modèles restent ici, et passent au-dessus du geste d'ouverture
 * pour rester utilisables sans ouvrir l'étape.
 */
export function ChainSteps({
  target,
  steps,
  problems,
  trace,
  failure,
  readOnly,
  onChange,
  onOpen,
}: {
  target: WorkTarget;
  steps: ChainStep[];
  problems: StepProblem[];
  /** Message après chaque étape, à son rang ; absent tant qu'on n'a pas lancé l'essai. */
  trace?: unknown[];
  /** L'étape qui a refusé, s'il y en a une. */
  failure?: { step: number; evaluation: { code: string; path: string | null } };
  /** Sur la racine : les étapes se lisent, sans boutons pour les changer. */
  readOnly: boolean;
  onChange: (steps: ChainStep[]) => void;
  onOpen: (name: string) => void;
}) {
  const { t } = useTranslation();
  const models = useDataModels(target);
  const known = models.data ?? [];

  function update(index: number, change: Partial<ChainStep>) {
    onChange(steps.map((s, i) => (i === index ? { ...s, ...change } : s)));
  }

  function add() {
    onChange([
      ...steps,
      {
        name: `etape-${steps.length + 1}`,
        // Un template vide ne compilerait pas : l'étape naît sur l'identité.
        template: "{ }",
        target: null,
        source_model: null,
        destination_model: null,
      },
    ]);
  }

  return (
    <section aria-labelledby="chain-steps">
      <h2 id="chain-steps">{t("chains.editor.steps")}</h2>
      {steps.length === 0 && <p className="muted">{t("chains.editor.noStep")}</p>}
      <ol className="card-list plain-list">
        {steps.map((step, index) => (
          <li
            key={index}
            className="row row-openable"
            aria-label={t("chains.editor.step", { rank: index + 1 })}
          >
            <div className="row-main">
              <span className="badge badge-accent">{index + 1}</span>{" "}
              <button type="button" className="row-open" onClick={() => onOpen(step.name)}>
                {step.name}
              </button>
              <div className="row-sub">
                {t("chains.steps.summary", {
                  source: labelOf(known, step.source_model) ?? t("chains.steps.noModel"),
                  destination: labelOf(known, step.destination_model) ?? t("chains.steps.noModel"),
                })}
                {step.target !== null && ` · ${step.target}`}
              </div>
            </div>
            {/* Au-dessus du bouton qui couvre la ligne : choisir un modèle ne doit pas
                ouvrir l'étape au passage. */}
            <div className="row-control" onClick={(e) => e.stopPropagation()} role="presentation">
              <ModelPicker
                caption={t("chains.fields.sourceModel")}
                models={known}
                value={step.source_model}
                readOnly={readOnly}
                onChange={(uri) => update(index, { source_model: uri })}
              />
            </div>
            <div className="row-control" onClick={(e) => e.stopPropagation()} role="presentation">
              <ModelPicker
                caption={t("chains.fields.destinationModel")}
                models={known}
                value={step.destination_model}
                readOnly={readOnly}
                onChange={(uri) => update(index, { destination_model: uri })}
              />
            </div>
            {!readOnly && (
              <div className="actions row-actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={index === 0}
                  onClick={() => onChange(moved(steps, index, index - 1))}
                >
                  {t("chains.editor.up")}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={index === steps.length - 1}
                  onClick={() => onChange(moved(steps, index, index + 1))}
                >
                  {t("chains.editor.down")}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => onChange(steps.filter((_, i) => i !== index))}
                >
                  {t("chains.editor.remove")}
                </button>
              </div>
            )}
            {failure?.step === index && (
              <p className="alert row-detail" role="alert">
                {t("chains.editor.failed", {
                  rank: index + 1,
                  code: failure.evaluation.code,
                  path: failure.evaluation.path ?? "",
                })}
              </p>
            )}
            {trace !== undefined && index < trace.length && (
              <div className="row-detail">
                <div className="caption">{t("chains.editor.after", { rank: index + 1 })}</div>
                <pre className="mono">{JSON.stringify(trace[index], null, 2)}</pre>
              </div>
            )}
            {problems
              .filter((p) => p.step === index)
              .map((p) => (
                <div key={`${p.code}-${p.detail ?? ""}`} className="alert row-detail" role="alert">
                  <p>
                    {t(`chains.problems.${p.code}`, {
                      detail: p.detail ?? "",
                      line: p.line,
                      column: p.column,
                    })}
                  </p>
                </div>
              ))}
          </li>
        ))}
      </ol>
      {!readOnly && (
        <div className="actions">
          <button type="button" className="btn btn-secondary" onClick={add}>
            {t("chains.editor.add")}
          </button>
        </div>
      )}
    </section>
  );
}
