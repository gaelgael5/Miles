import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type Chain,
  type ChainStep,
  type StepProblem,
  useChain,
  useCheckChain,
  useDeleteChain,
  useSaveChain,
} from "../api/chains";
import { ApiError } from "../api/http";
import type { WorkTarget } from "../api/workTarget";
import { ConfirmDialog } from "../layout/ConfirmDialog";
import { ChainStepsEditor } from "./ChainStepsEditor";

function savedProblems(error: unknown): StepProblem[] {
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail !== null) {
    const detail = error.detail as { code?: string; problems?: StepProblem[] };
    if (detail.code === "chaine_invalide") {
      return detail.problems ?? [];
    }
  }
  return [];
}

function parsedSample(text: string): { value: unknown } | null {
  if (!text.trim()) {
    // Pas d'échantillon : la source vaut {} (Gael, 22/10/2026).
    return { value: null };
  }
  try {
    return { value: JSON.parse(text) };
  } catch {
    return null;
  }
}

function Editor({ target, chain, onDeleted }: { target: WorkTarget; chain: Chain; onDeleted: () => void }) {
  const { t } = useTranslation();
  const save = useSaveChain(target, chain.slug);
  const check = useCheckChain();
  const remove = useDeleteChain(target, chain.slug);
  // Semé une fois depuis la chaîne lue : l'écran est remonté (clé) quand la chaîne change.
  const [label, setLabel] = useState(chain.label);
  const [steps, setSteps] = useState<ChainStep[]>(chain.steps);
  const [sample, setSample] = useState("");
  const [confirming, setConfirming] = useState(false);
  const sampleValue = parsedSample(sample);
  const problems = [...savedProblems(save.error), ...(check.data?.problems ?? [])];

  function test() {
    if (sampleValue !== null) {
      save.reset();
      check.mutate({ steps: steps.map((s) => ({ template: s.template, target: s.target })), sample: sampleValue.value });
    }
  }

  return (
    <>
      <label className="field">
        {t("chains.fields.label")}
        <input required readOnly={target.readOnly} value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <ChainStepsEditor steps={steps} problems={problems} readOnly={target.readOnly} onChange={setSteps} />
      <section className="card" aria-labelledby="chain-test">
        <h2 id="chain-test">{t("chains.editor.test")}</h2>
        <label className="field">
          {t("chains.fields.sample")}
          <textarea rows={6} spellCheck={false} value={sample} onChange={(e) => setSample(e.target.value)} />
        </label>
        {sampleValue === null && <p className="alert" role="alert">{t("chains.editor.sampleInvalid")}</p>}
        <div className="actions">
          <button type="button" className="btn btn-secondary" disabled={sampleValue === null || check.isPending} onClick={test}>
            {t("chains.editor.run")}
          </button>
        </div>
        {check.data?.failure && (
          <p className="alert" role="alert">
            {t("chains.editor.failed", {
              rank: check.data.failure.step + 1,
              code: check.data.failure.evaluation.code,
              path: check.data.failure.evaluation.path ?? "",
            })}
          </p>
        )}
        {check.data?.valid && !check.data.failure && (
          <ol className="plain-list">
            {check.data.trace.map((message, index) => (
              <li key={index}>
                <div className="caption">{t("chains.editor.after", { rank: index + 1 })}</div>
                <pre className="mono">{JSON.stringify(message, null, 2)}</pre>
              </li>
            ))}
          </ol>
        )}
      </section>
      {save.isSuccess && <p className="muted" role="status">{t("chains.editor.saved")}</p>}
      {save.isError && problems.length === 0 && (
        <p className="alert" role="alert">{t("chains.errors.unexpected")}</p>
      )}
      {/* L'essai sur échantillon reste offert sur la racine : il n'écrit rien. */}
      {!target.readOnly && (
      <div className="actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={save.isPending}
          onClick={() => {
            check.reset();
            save.mutate({ label, steps });
          }}
        >
          {t("chains.editor.save")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => setConfirming(true)}>
          {t("chains.editor.delete")}
        </button>
      </div>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("chains.editor.deleteTitle")}
          confirmLabel={t("chains.editor.delete")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate(undefined, { onSuccess: onDeleted });
          }}
        >
          {t("chains.editor.deleteBody", { slug: chain.slug })}
        </ConfirmDialog>
      )}
    </>
  );
}

/** Une chaîne de transformations : ses étapes, l'essai sur un échantillon, l'enregistrement. */
export function ChainScreen({
  target,
  slug,
  onBack,
}: {
  target: WorkTarget;
  slug: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const chain = useChain(target, slug);

  return (
    <section aria-labelledby="chain-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("chains.back")}
      </button>
      <h1 id="chain-title">
        {chain.data?.label ?? slug} <span className="mono muted">transformations/{slug}</span>
      </h1>
      {chain.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {chain.isError && <p className="alert" role="alert">{t("chains.errors.unreadable")}</p>}
      {chain.data && <Editor key={slug} target={target} chain={chain.data} onDeleted={onBack} />}
    </section>
  );
}
