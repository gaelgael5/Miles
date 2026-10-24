import { useState } from "react";
import { useTranslation } from "react-i18next";

import { type Chain, type ChainStep, useSaveChain } from "../api/chains";
import { useDataModels } from "../api/dataModels";
import type { WorkTarget } from "../api/workTarget";
import { useSaveShortcut } from "../layout/useSaveShortcut";
import { modelUri } from "../dataModels/schemaText";

/**
 * Une étape en page pleine (Gael, 24/10/2026) : c'est ici qu'on travaille la
 * transformation, loin de la liste qui n'en donne que le résumé.
 *
 * L'enregistrement passe par la chaîne entière : une étape n'a pas d'existence propre
 * côté serveur — elle vit dans `chain.json` et son fichier de template.
 */
export function ChainStepScreen({
  target,
  chain,
  step,
  onBack,
}: {
  target: WorkTarget;
  chain: Chain;
  step: ChainStep;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const save = useSaveChain(target, chain.slug);
  const models = useDataModels(target);
  const [name, setName] = useState(step.name);
  const [template, setTemplate] = useState(step.template);
  const [stepTarget, setStepTarget] = useState(step.target ?? "");
  const dirty =
    name !== step.name || template !== step.template || stepTarget !== (step.target ?? "");

  function labelOf(uri: string | null): string {
    if (uri === null) {
      return t("chains.steps.noModel");
    }
    const found = (models.data ?? []).find((m) => modelUri(m.scope, m.name) === uri);
    return found ? (found.label ?? found.name) : uri;
  }

  function saveStep() {
    const steps = chain.steps.map((s) =>
      s.name === step.name ? { ...s, name, template, target: stepTarget || null } : s,
    );
    // Renommer une étape renomme son fichier de template : on revient à la chaîne, dont
    // la relecture donnera la nouvelle liste. Rester ici pointerait un nom disparu.
    save.mutate({ label: chain.label, steps }, { onSuccess: name === step.name ? undefined : onBack });
  }

  // Ctrl+S fait ce que fait le bouton, aux mêmes conditions (story caad743d).
  const canSave = !target.readOnly && dirty && !save.isPending;
  useSaveShortcut(canSave ? saveStep : null);

  return (
    <section aria-labelledby="chain-step-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("chains.steps.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="chain-step-title">{step.name}</h1>
          <p className="lead">
            <span className="mono">{chain.slug}</span> ·{" "}
            {t("chains.steps.summary", {
              source: labelOf(step.source_model),
              destination: labelOf(step.destination_model),
            })}
          </p>
        </div>
        {!target.readOnly && (
          <div className="actions">
            {dirty && <span className="badge badge-warning">{t("chains.editor.unsaved")}</span>}
            <button
              type="button"
              className="btn btn-primary"
              disabled={!canSave}
              title={t("chains.editor.saveShortcut")}
              onClick={saveStep}
            >
              {t("chains.editor.save")}
            </button>
          </div>
        )}
      </div>
      {save.isError && (
        <p className="alert" role="alert">
          {t("chains.errors.unexpected")}
        </p>
      )}
      {save.isSuccess && !dirty && (
        <p className="notice" role="status">
          {t("chains.editor.saved")}
        </p>
      )}
      <div className="card">
        <label className="field">
          {t("chains.fields.stepName")}
          <input
            className="mono"
            readOnly={target.readOnly}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="field">
          {t("chains.fields.template")}
          <textarea
            rows={20}
            spellCheck={false}
            className="mono"
            readOnly={target.readOnly}
            value={template}
            onChange={(event) => setTemplate(event.target.value)}
          />
        </label>
        <label className="field">
          {t("chains.fields.target")}
          <input
            className="mono"
            placeholder="$.chemin"
            readOnly={target.readOnly}
            value={stepTarget}
            onChange={(event) => setStepTarget(event.target.value)}
          />
        </label>
        <p className="help">{t("chains.editor.targetHelp")}</p>
      </div>
    </section>
  );
}
