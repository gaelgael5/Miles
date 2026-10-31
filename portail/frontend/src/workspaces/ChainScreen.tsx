import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import {
  type Chain,
  type ChainStep,
  useChain,
  useChainSample,
  useCheckChain,
  useDeleteChain,
  useSaveChain,
  useSaveChainSample,
} from "../api/chains";
import type { WorkTarget } from "../api/workTarget";
import { useSaveShortcut } from "../layout/useSaveShortcut";
import { ChainSample, parsedSample } from "./ChainSample";
import { savedProblems } from "./chainProblems";
import { ChainStepScreen } from "./ChainStepScreen";
import { ChainSteps } from "./ChainSteps";

function Editor({
  target,
  chain,
  onDeleted,
  onOpenStep,
}: {
  target: WorkTarget;
  chain: Chain;
  onDeleted: () => void;
  onOpenStep: (name: string | null) => void;
}) {
  const { t } = useTranslation();
  const save = useSaveChain(target, chain.slug);
  const check = useCheckChain();
  const remove = useDeleteChain(target, chain.slug);
  const stored = useChainSample(target, chain.slug);
  const saveSample = useSaveChainSample(target, chain.slug);
  // Semé une fois depuis la chaîne lue : l'écran est remonté (clé) quand la chaîne change.
  const [label, setLabel] = useState(chain.label);
  const [steps, setSteps] = useState<ChainStep[]>(chain.steps);
  const [confirming, setConfirming] = useState(false);
  const sample = stored.data?.sample ?? null;
  const sampleValue = parsedSample(sample ?? "");
  const problems = [...savedProblems(save.error), ...(check.data?.problems ?? [])];

  function saveChain() {
    check.reset();
    save.mutate({ label, steps });
  }

  // Ctrl+S fait ce que fait le bouton, aux mêmes conditions (story caad743d).
  const canSave = !target.readOnly && !save.isPending;
  useSaveShortcut(canSave ? saveChain : null);

  function test() {
    if (sampleValue !== null) {
      save.reset();
      check.mutate({ steps: steps.map((s) => ({ template: s.template, target: s.target })), sample: sampleValue.value });
    }
  }

  return (
    <>
      {/* L'en-tête vit ici, avec l'état de l'édition : « Enregistrer » y est en haut à
          droite (story caad743d). */}
      <div className="page-head">
        <div>
          <h1 id="chain-title">
            {chain.label} <span className="mono muted">transformations/{chain.slug}</span>
          </h1>
        </div>
        {!target.readOnly && (
          <div className="actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={!canSave}
              title={t("dataModels.editor.saveShortcut")}
              onClick={saveChain}
            >
              {t("chains.editor.save")}
            </button>
          </div>
        )}
      </div>
      {save.isSuccess && <p className="notice" role="status">{t("chains.editor.saved")}</p>}
      {save.isError && problems.length === 0 && (
        <p className="alert" role="alert">{t("chains.errors.unexpected")}</p>
      )}
      <label className="field">
        {t("chains.fields.label")}
        <input required readOnly={target.readOnly} value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <section className="card" aria-labelledby="chain-test">
        <h2 id="chain-test">{t("chains.editor.test")}</h2>
        <ChainSample
          sample={sample}
          readOnly={target.readOnly}
          pending={saveSample.isPending}
          onSave={(next) => saveSample.mutate(next)}
        />
        {sampleValue === null && <p className="alert" role="alert">{t("chains.editor.sampleInvalid")}</p>}
        <div className="actions">
          <button type="button" className="btn btn-secondary" disabled={sampleValue === null || check.isPending} onClick={test}>
            {t("chains.editor.run")}
          </button>
        </div>
        {/* Le résultat de chaque étape s'affiche DANS la ligne de l'étape qui l'a
            produit (Gael, 24/10/2026) : sous le bouton, il fallait recompter les rangs
            pour savoir à quoi se rapportait quoi. */}
      </section>
      <ChainSteps
        target={target}
        steps={steps}
        problems={problems}
        trace={check.data?.valid && !check.data.failure ? check.data.trace : undefined}
        failure={check.data?.failure ?? undefined}
        readOnly={target.readOnly}
        onChange={setSteps}
        onOpen={onOpenStep}
      />
      {/* L'essai sur échantillon reste offert sur la racine : il n'écrit rien. */}
      {!target.readOnly && (
        <div className="actions">
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
  step,
  onOpenStep,
  onBack,
}: {
  target: WorkTarget;
  slug: string;
  /** Étape ouverte en page pleine ; absente : la chaîne elle-même. */
  step?: string;
  onOpenStep: (name: string | null) => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const chain = useChain(target, slug);
  const opened = chain.data?.steps.find((s) => s.name === step);
  if (chain.data && step !== undefined && opened !== undefined) {
    return (
      <ChainStepScreen
        target={target}
        chain={chain.data}
        step={opened}
        onBack={() => onOpenStep(null)}
      />
    );
  }

  return (
    <section aria-labelledby="chain-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("chains.back")}
      </button>
      {!chain.data && (
        <h1 id="chain-title">
          {slug} <span className="mono muted">transformations/{slug}</span>
        </h1>
      )}
      {chain.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {chain.isError && <p className="alert" role="alert">{t("chains.errors.unreadable")}</p>}
      {chain.data && (
        <Editor
          key={slug}
          target={target}
          chain={chain.data}
          onDeleted={onBack}
          onOpenStep={onOpenStep}
        />
      )}
    </section>
  );
}
