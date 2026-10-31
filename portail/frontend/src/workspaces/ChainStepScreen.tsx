import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { type Chain, type ChainStep, useChainSample, useCheckChain, useSaveChain } from "../api/chains";
import { useDataModels, useModelExample, useModelPaths } from "../api/dataModels";
import type { WorkTarget } from "../api/workTarget";
import { useSaveShortcut } from "../layout/useSaveShortcut";
import { modelUri, targetOf } from "../dataModels/schemaText";
import { caretOf, placeCaret, withInsertion } from "../dataModels/caretInsert";
import { parsedSample } from "./ChainSample";
import { SampleExplorer } from "./SampleExplorer";
import { StepProblems, savedProblems } from "./chainProblems";

// Le Web Component et ses assets ne se chargent qu'ici : le reste du portail ne les paie pas.
const JsltEditor = lazy(() => import("../dataModels/JsltEditor"));

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
  const stored = useChainSample(target, chain.slug);
  const check = useCheckChain();
  const example = useModelExample(target);
  // Les chemins du modèle SOURCE : c'est le document que le template lit.
  const source = targetOf(step.source_model ?? "");
  const sourcePaths = useModelPaths(target, source?.[0] ?? null, source?.[1] ?? null);
  // Pourquoi l'exécution n'a rien donné. Un `return` muet laissait croire que le
  // template rendait null, alors que c'est l'échantillon qui manquait (Gael, 31/10/2026).
  const [blocked, setBlocked] = useState<string | null>(null);
  const [exploring, setExploring] = useState(false);
  // Le curseur au moment d'ouvrir la fenêtre : l'ouvrir déplace le focus, et c'est là
  // que l'utilisateur veut voir arriver le chemin.
  const editorHost = useRef<HTMLDivElement>(null);
  const caret = useRef<{ start: number; end: number } | null>(null);
  const [replaced, setReplaced] = useState<number | null>(null);
  const sampleValue = parsedSample(stored.data?.sample ?? "");
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

  function openSource() {
    setBlocked(null);
    if (stored.isPending) {
      setBlocked("chains.steps.cannotRunLoading");
      return;
    }
    if (sampleValue === null) {
      // Dire pourquoi, plutôt que de ne pas armer le raccourci : une touche sans effet
      // est le défaut qu'on vient de corriger sur F5, on ne le réintroduit pas ici.
      setBlocked("chains.explorer.noSample");
      return;
    }
    caret.current = caretOf(editorHost.current);
    setExploring(true);
  }

  function insertPath(path: string) {
    // Le chemin remplace la sélection, ou se pose au curseur. On referme : prendre un
    // chemin est un geste de saisie, pas une consultation — rester ouvert obligerait à
    // fermer à la main avant de continuer à écrire.
    const next = withInsertion(template, path, caret.current);
    setTemplate(next.text);
    setExploring(false);
    setReplaced(next.caret);
  }

  function fillFromDestination() {
    const destination = targetOf(step.destination_model ?? "");
    if (destination === null) {
      return;
    }
    example.mutate(
      { scope: destination[0], name: destination[1] },
      // Indenté à deux espaces, comme le template : on le relit et on le retouche.
      { onSuccess: (got) => setTemplate(JSON.stringify(got.example, null, 2)) },
    );
  }

  function run() {
    setBlocked(null);
    if (stored.isPending) {
      // Exécuter maintenant porterait sur rien et ferait croire que le template rend
      // null. On le DIT : un bouton qui ne fait rien est pire qu'un bouton qui refuse.
      setBlocked("chains.steps.cannotRunLoading");
      return;
    }
    const sample = stored.data?.sample ?? "";
    let parsed: unknown = null;
    try {
      // Un échantillon vide est légitime : la source vaut alors null.
      parsed = sample.trim() === "" ? null : JSON.parse(sample);
    } catch {
      // L'écran de la chaîne le dit, mais pas CELUI-CI : la personne y travaille sans
      // voir l'autre, et son F5 restait sans effet et sans explication.
      setBlocked("chains.steps.cannotRunSample");
      return;
    }
    // La seule étape, sur l'échantillon : on éprouve CE template, pas la chaîne entière.
    check.mutate({ steps: [{ template, target: stepTarget || null }], sample: parsed });
  }

  useEffect(() => {
    if (replaced === null) {
      return;
    }
    // Après le rendu : l'effet de l'éditeur a déjà réécrit sa valeur, et le curseur se
    // pose derrière le chemin inséré pour que la frappe continue sans un clic.
    placeCaret(editorHost.current, replaced);
    setReplaced(null);
  }, [replaced]);

  // Ce qui bloque, du refus d'enregistrement comme de la compilation à l'exécution :
  // les deux sont des problèmes d'étape et se lisent au même endroit.
  const problems = [...savedProblems(save.error), ...(check.data?.problems ?? [])];

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
            {" · "}
            {/* Sur quoi F5 exécute : sans cela, on lance sans savoir. */}
            {stored.isPending
              ? t("chains.steps.sampleLoading")
              : stored.data?.sample
                ? t("chains.steps.sampleReady")
                : t("chains.steps.sampleMissing")}
          </p>
        </div>
        {!target.readOnly && (
          <div className="actions">
            {dirty && <span className="badge badge-warning">{t("chains.editor.unsaved")}</span>}
            <button
              type="button"
              className="btn btn-secondary"
              disabled={step.destination_model === null || example.isPending}
              title={t("chains.steps.fillHelp")}
              onClick={fillFromDestination}
            >
              {t("chains.steps.fill")}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={check.isPending}
              title={t("chains.steps.runHelp")}
              onClick={run}
            >
              {t("chains.steps.run")}
            </button>
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
      {save.isError && problems.length === 0 && (
        <p className="alert" role="alert">
          {t("chains.errors.unexpected")}
        </p>
      )}
      {save.isError && problems.length > 0 && (
        <p className="alert" role="alert">
          {t("chains.editor.refused")}
        </p>
      )}
      {blocked !== null && (
        <p className="alert" role="alert">
          {t(blocked)}
        </p>
      )}
      <StepProblems problems={problems} />
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
        <div className="field">
          {t("chains.fields.template")}
          <div ref={editorHost}>
            <Suspense fallback={<p className="muted">{t("dataModels.loading")}</p>}>
              <JsltEditor
                value={template}
                onChange={setTemplate}
                onRun={run}
                onOpenSource={openSource}
                readOnly={target.readOnly}
                ariaLabel={t("chains.fields.template")}
                paths={sourcePaths.data?.paths}
              />
            </Suspense>
          </div>
          {/* Le raccourci se DIT : un geste qui ne s'annonce nulle part n'est connu que
              de celui qui l'a écrit. Le bouton qu'il remplace, lui, se voyait. */}
          <p className="help">{t("chains.explorer.shortcut")}</p>
        </div>
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
      {check.data?.failure && (
        <p className="alert" role="alert">
          {t("chains.editor.failed", {
            rank: 1,
            code: check.data.failure.evaluation.code,
            path: check.data.failure.evaluation.path ?? "",
          })}
        </p>
      )}
      {exploring && sampleValue !== null && (
        <SampleExplorer
          sample={sampleValue.value}
          onInsert={insertPath}
          onClose={() => setExploring(false)}
        />
      )}
      {check.data?.valid && !check.data.failure && (
        <div className="card">
          <h2>{t("chains.steps.result")}</h2>
          <pre className="mono">{JSON.stringify(check.data.trace.at(-1), null, 2)}</pre>
        </div>
      )}
    </section>
  );
}
