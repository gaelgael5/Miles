import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import { SHARED_SCOPE } from "../api/dataModels";
import type { WorkTarget } from "../api/workTarget";
import {
  type EventPerimeter,
  type EventType,
  useDeleteEventType,
} from "../api/workflowEvents";
import { ModelRefusal } from "../workspaces/ModelRefusal";
import { EditForm } from "./EventForms";

/** Le nom lisible d'un périmètre : « Transverse » pour `shared`, sinon le domaine. */
export function perimeterLabel(t: (key: string) => string, scope: string): string {
  return scope === SHARED_SCOPE ? t("dataModels.list.shared") : scope;
}

function EventRow({
  target,
  declared,
  onOpenModel,
}: {
  target: WorkTarget;
  declared: EventType;
  onOpenModel: () => void;
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const [editing, setEditing] = useState(false);
  const remove = useDeleteEventType(target);

  return (
    <li className="row row-openable">
      <div className="row-main">
        <div className="row-title">{declared.label}</div>
        {/* Le nom du DSL, pas le libellé : c'est lui qu'on écrit dans un `DEFINE EVENT`,
            et la seule chose qu'un script de workflow connaisse de cet écran. */}
        <div className="row-sub mono">{declared.name}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("workflowEvents.list.model")}</div>
        {/* Le modèle est un modèle ORDINAIRE depuis le 14/11/2026 : il s'édite par l'écran
            des modèles, et non par un éditeur propre aux events qui n'existe plus. */}
        <button type="button" className="value row-open" onClick={onOpenModel}>
          <span className="mono">{declared.model}</span>
        </button>
      </div>
      <div className="cell">
        <div className="caption">{t("workflowEvents.list.unique")}</div>
        <div className="value mono">
          {declared.unique.length > 0
            ? declared.unique.join(", ")
            : t("workflowEvents.list.noDedup")}
        </div>
      </div>
      {/* Une déclaration dont le modèle a disparu bloque l'enregistrement d'une version :
          le dire ICI, c'est le dire là où on peut la corriger. */}
      {declared.model_missing && (
        <span className="badge badge-danger">{t("workflowEvents.list.modelMissing")}</span>
      )}
      <div className="actions row-actions">
        {!target.readOnly && (
          <>
            <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)}>
              {t("workflowEvents.list.edit")}
            </button>
            <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
              {t("dataModels.list.delete")}
            </button>
          </>
        )}
      </div>
      {editing && (
        <div className="row-detail">
          <EditForm
            target={target}
            declared={declared}
            onSaved={() => setEditing(false)}
            onCancel={() => setEditing(false)}
          />
        </div>
      )}
      {remove.isError && (
        <div className="row-detail">
          <ModelRefusal error={remove.error} />
        </div>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("workflowEvents.deleteConfirm.title")}
          confirmLabel={t("dataModels.deleteConfirm.confirm")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate(declared);
          }}
        >
          <p>{t("workflowEvents.deleteConfirm.body", { name: declared.name })}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

/**
 * Le référentiel d'UN périmètre : son artefact, et ce qu'il déclare.
 *
 * Trois états, et ils ne se corrigent pas de la même façon (story `8a9ff6bc`) :
 * l'artefact ne se relit pas — on NOMME le fichier et on donne les positions du moteur,
 * sans masquer les autres périmètres ; il n'en a aucun — l'invitation à en déclarer un,
 * et pas une page blanche ; il en a — la liste.
 */
export function PerimeterSection({
  target,
  perimeter,
  onOpenModel,
}: {
  target: WorkTarget;
  perimeter: EventPerimeter;
  onOpenModel: (declared: EventType) => void;
}) {
  const { t } = useTranslation();
  const name = perimeterLabel(t, perimeter.scope);
  const broken = perimeter.problems.length > 0;

  return (
    <section className="card" aria-label={t("workflowEvents.perimeter.region", { name })}>
      <div className="page-head">
        <div>
          <h2>{name}</h2>
          {/* Le fichier, toujours : c'est lui qu'on ouvre pour comprendre, et lui que le
              moteur chargera. Un périmètre sans aucun type ne l'a pas encore. */}
          <p className="row-sub mono">{perimeter.path}</p>
        </div>
      </div>
      {broken && (
        <div className="notice notice-danger" role="note">
          <p>{t("workflowEvents.perimeter.unreadable", { path: perimeter.path })}</p>
          <ul className="plain-list">
            {perimeter.problems.map((problem) => (
              <li key={`${problem.line}:${problem.column}:${problem.message}`} className="mono">
                {t("workflowEvents.perimeter.at", {
                  line: problem.line,
                  column: problem.column,
                  message: problem.message,
                })}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!broken && perimeter.types.length === 0 && (
        <p className="muted">{t("workflowEvents.perimeter.empty")}</p>
      )}
      {perimeter.types.length > 0 && (
        <ul className="card-list plain-list">
          {perimeter.types.map((d) => (
            <EventRow
              key={`${d.scope}/${d.name}`}
              target={target}
              declared={d}
              onOpenModel={() => onOpenModel(d)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
