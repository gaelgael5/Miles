import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import { proposeDslName } from "../api/contracts";
import type { WorkTarget } from "../api/workTarget";
import {
  type Workflow,
  useCreateWorkflow,
  useDeleteWorkflow,
  useWorkflows,
} from "../api/workflows";
import type { Workspace } from "../api/workspaces";
import { ModelRefusal } from "./ModelRefusal";

/**
 * Les champs refusés qui ne veulent pas dire ici ce qu'ils veulent dire ailleurs.
 *
 * `name` est le cas qui mord : le libellé partagé parle d'un slug « tirets et soulignés »,
 * or le DSL du moteur refuse le tiret. Sans cette redirection, l'écran expliquerait à
 * l'utilisateur qu'il a droit à un caractère que le serveur vient de lui refuser.
 */
const REFUSED_FIELDS = {
  name: "workflows.errors.invalid.name",
  name_non_ecrivable: "workflows.errors.invalid.nameReserved",
  nom_de_perimetre: "workflows.errors.invalid.perimeterName",
};

/**
 * Création en deux temps, comme un modèle (Gael, 23/10/2026) : le libellé et le nom ici,
 * le comportement — états et transitions — sur l'écran du workflow.
 *
 * Le fichier écrit par ce geste est chargeable par le moteur tel quel : `NAME <clef>`
 * seul est un script complet valide (mesuré le 16/11/2026 sur urban-workflow 0.4.0).
 * Sans cette propriété, un workflow créé puis laissé de côté casserait le chargement de
 * tout le répertoire entre les deux gestes.
 */
function CreateForm({
  target,
  onCreated,
  onCancel,
}: {
  target: WorkTarget;
  onCreated: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const create = useCreateWorkflow(target);
  const [label, setLabel] = useState("");
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const shownName = touched ? name : proposeDslName(label);

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate({ name: shownName, label }, { onSuccess: onCreated });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("workflows.form.title")}>
      <h2>{t("workflows.form.title")}</h2>
      <label className="field">
        {t("workflows.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label className="field">
        {t("workflows.fields.name")}
        <input
          required
          className="mono"
          value={shownName}
          onChange={(e) => {
            setTouched(true);
            setName(e.target.value);
          }}
        />
      </label>
      <p className="help">{t("workflows.fields.nameHelp")}</p>
      {create.isError && <ModelRefusal error={create.error} fields={REFUSED_FIELDS} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={create.isPending}>
          {t("workflows.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

/** Une ligne de la liste : ce que le script annonce, ou ce qui l'empêche de se relire. */
function WorkflowRow({ target, workflow }: { target: WorkTarget; workflow: Workflow }) {
  const { t } = useTranslation();
  const remove = useDeleteWorkflow(target);
  const [confirming, setConfirming] = useState(false);
  const broken = workflow.problems.length > 0;

  return (
    <li className="card">
      {/* Pas de ligne cliquable ici, et c'est délibéré : l'écran d'écriture d'un script
          — états, transitions — est une story à part. Une ligne qui s'ouvre sur rien
          promettrait un geste qui n'existe pas. */}
      <div className="row-head">
        <div>
          <h2 className="mono">{workflow.name}</h2>
          <p className="lead">{workflow.label ?? t("workflows.list.unreadable")}</p>
        </div>
        {!broken && (
          <dl className="row-facts">
            <dt>{t("workflows.list.states")}</dt>
            <dd>{workflow.states}</dd>
            <dt>{t("workflows.list.version")}</dt>
            <dd>{workflow.version ?? t("workflows.list.noVersion")}</dd>
            <dt>{t("workflows.list.includes")}</dt>
            {/* Dans l'ordre écrit, jamais trié : le chargeur du moteur visite les
                fragments dans cet ordre, et deux ordres peuvent résoudre deux choses
                différentes. */}
            <dd className="mono">
              {workflow.includes.length > 0
                ? workflow.includes.join(", ")
                : t("workflows.list.noIncludes")}
            </dd>
          </dl>
        )}
      </div>
      {broken && (
        <ul className="problems" aria-label={t("workflows.list.problems")}>
          {workflow.problems.map((problem) => (
            <li key={`${problem.line}:${problem.column}:${problem.message}`}>
              <span className="mono">
                {problem.line}:{problem.column}
              </span>{" "}
              {problem.message}
            </li>
          ))}
        </ul>
      )}
      {!target.readOnly && (
        <div className="actions row-actions">
          <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
            {t("dataModels.list.delete")}
          </button>
        </div>
      )}
      {remove.isError && (
        <div className="row-detail">
          <ModelRefusal error={remove.error} />
        </div>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("workflows.deleteConfirm.title")}
          confirmLabel={t("dataModels.deleteConfirm.confirm")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate(workflow.name);
          }}
        >
          {/* Le FICHIER est nommé : c'est lui qu'on retire, et son nom est ce qu'un
              `INCLUDE` d'un autre script aurait écrit. */}
          <p>{t("workflows.deleteConfirm.body", { name: workflow.name })}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

/**
 * Les scripts de workflow de la branche (story 69036d69).
 *
 * Ce que cet écran NE fait pas, et c'est la frontière posée par Gael le 12/11/2026 : il
 * n'évalue rien. « c'est environnement qui fera les évaluations du workflow quand les
 * events seront traités. » Ici on écrit et on diagnostique.
 */
export function WorkflowsScreen({
  workspace,
  target,
  onBack,
}: {
  workspace: Workspace;
  target: WorkTarget;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const workflows = useWorkflows(target);
  const [creating, setCreating] = useState(false);

  return (
    <section aria-labelledby="workflows-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="workflows-title">{t("workflows.title", { name: workspace.name })}</h1>
          <p className="lead">
            {t("workflows.intro")} <span className="mono">{workspace.work_branch}</span>
          </p>
        </div>
        {!target.readOnly && !creating && (
          <div className="actions">
            <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
              {t("workflows.add")}
            </button>
          </div>
        )}
      </div>
      {creating && (
        <CreateForm
          target={target}
          onCreated={() => setCreating(false)}
          onCancel={() => setCreating(false)}
        />
      )}
      {workflows.isPending && (
        <p className="muted" role="status">
          {t("dataModels.loading")}
        </p>
      )}
      {workflows.isError && <ModelRefusal error={workflows.error} />}
      {workflows.isSuccess && workflows.data.length === 0 && (
        <p className="muted">{t("workflows.empty")}</p>
      )}
      {workflows.isSuccess && workflows.data.length > 0 && (
        <ul className="card-list plain-list">
          {workflows.data.map((workflow) => (
            <WorkflowRow key={workflow.name} target={target} workflow={workflow} />
          ))}
        </ul>
      )}
    </section>
  );
}
