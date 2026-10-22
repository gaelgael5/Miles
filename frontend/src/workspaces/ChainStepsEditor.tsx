import { useTranslation } from "react-i18next";

import type { ChainStep, StepProblem } from "../api/chains";

function moved(steps: ChainStep[], from: number, to: number): ChainStep[] {
  const next = [...steps];
  const [step] = next.splice(from, 1);
  if (step !== undefined) {
    next.splice(to, 0, step);
  }
  return next;
}

/**
 * Étapes d'une chaîne, dans l'ordre d'application choisi par l'utilisateur. Chaque étape :
 * un nom (qui devient le nom de son fichier de template), un template, une cible.
 */
export function ChainStepsEditor({
  steps,
  problems,
  onChange,
}: {
  steps: ChainStep[];
  problems: StepProblem[];
  onChange: (steps: ChainStep[]) => void;
}) {
  const { t } = useTranslation();

  function update(index: number, change: Partial<ChainStep>) {
    onChange(steps.map((s, i) => (i === index ? { ...s, ...change } : s)));
  }

  function add() {
    onChange([...steps, { name: `etape-${steps.length + 1}`, template: "{ }", target: null }]);
  }

  return (
    <section aria-labelledby="chain-steps">
      <h2 id="chain-steps">{t("chains.editor.steps")}</h2>
      {steps.length === 0 && <p className="muted">{t("chains.editor.noStep")}</p>}
      <ol className="plain-list">
        {steps.map((step, index) => (
          <li key={index} className="card" aria-label={t("chains.editor.step", { rank: index + 1 })}>
            <div className="actions">
              <span className="badge badge-accent">{index + 1}</span>
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
            <label className="field">
              {t("chains.fields.stepName")}
              <input value={step.name} onChange={(e) => update(index, { name: e.target.value })} />
            </label>
            <label className="field">
              {t("chains.fields.template")}
              <textarea
                rows={6}
                spellCheck={false}
                value={step.template}
                onChange={(e) => update(index, { template: e.target.value })}
              />
            </label>
            <label className="field">
              {t("chains.fields.target")}
              <input
                className="mono"
                placeholder="$.chemin"
                value={step.target ?? ""}
                onChange={(e) => update(index, { target: e.target.value || null })}
              />
            </label>
            <p className="help">{t("chains.editor.targetHelp")}</p>
            {problems
              .filter((p) => p.step === index)
              .map((p) => (
                <div key={`${p.code}-${p.detail ?? ""}`} className="alert" role="alert">
                  <p>
                    {t(`chains.problems.${p.code}`, { detail: p.detail ?? "", line: p.line, column: p.column })}
                  </p>
                  {p.violations.length > 0 && (
                    <ul>
                      {p.violations.map((v) => (
                        <li key={`${v.construction}-${v.line}-${v.column}`}>
                          {t("chains.problems.violation", {
                            construction: v.construction,
                            detail: v.detail ?? "",
                            line: v.line ?? "?",
                            column: v.column ?? "?",
                          })}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
          </li>
        ))}
      </ol>
      <div className="actions">
        <button type="button" className="btn btn-secondary" onClick={add}>
          {t("chains.editor.add")}
        </button>
      </div>
    </section>
  );
}
