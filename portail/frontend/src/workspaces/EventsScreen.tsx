import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { WorkTarget } from "../api/workTarget";
import { type EventType, useEventPerimeters } from "../api/workflowEvents";
import type { Workspace } from "../api/workspaces";
import { DeclareForm } from "../events/EventForms";
import { PerimeterSection, perimeterLabel } from "../events/PerimeterSection";
import { DomainForm } from "./DomainForm";
import { ModelRefusal } from "./ModelRefusal";

/**
 * Référentiel des types d'event du workspace, PÉRIMÈTRE PAR PÉRIMÈTRE.
 *
 * Ce que cet écran produit, c'est le `DEFINE EVENT … AS @modele` de l'artefact d'un
 * périmètre — et non plus un document de schéma : depuis le 14/11/2026, le payload d'un
 * type d'event est un modèle de données ordinaire, qui s'édite par l'écran des modèles.
 *
 * Par périmètre depuis le 17/11/2026 (Gael, 12/11/2026 : « on a des sous-menus qui
 * permettent quand on clique sur le lien de lire les différents fichier d'artefacts pour
 * afficher les referentiels »). Sans `scope`, tous les périmètres se suivent sur la page ;
 * avec, un seul — celui que le menu a ouvert. Les deux lisent la MÊME requête, donc passer
 * de l'un à l'autre ne coûte aucun accès au dépôt.
 */
export function EventsScreen({
  workspace,
  target,
  scope,
  onBack,
  onOpenModel,
}: {
  workspace: Workspace;
  target: WorkTarget;
  /** Périmètre ouvert depuis le menu ; absent : tous. */
  scope?: string;
  onBack: () => void;
  onOpenModel: (declared: EventType) => void;
}) {
  const { t } = useTranslation();
  const perimeters = useEventPerimeters(target);
  const [creating, setCreating] = useState(false);
  const [addingDomain, setAddingDomain] = useState(false);
  const [added, setAdded] = useState<string | null>(null);
  const all = perimeters.data ?? [];
  const shown = scope === undefined ? all : all.filter((p) => p.scope === scope);

  return (
    <section aria-labelledby="workflow-events-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="workflow-events-title">
            {scope === undefined
              ? t("workflowEvents.title", { name: workspace.name })
              : t("workflowEvents.perimeter.title", { name: perimeterLabel(t, scope) })}
          </h1>
          <p className="lead">
            {t("workflowEvents.intro")} <span className="mono">{workspace.work_branch}</span>
          </p>
        </div>
        {!target.readOnly && (
          <div className="actions">
            {/* Ajouter un domaine n'a de sens que sur la vue d'ensemble : depuis un
                périmètre ouvert, c'est le périmètre d'à côté qu'on créerait. */}
            {scope === undefined && !addingDomain && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setAdded(null);
                  setAddingDomain(true);
                }}
              >
                {t("dataModels.addDomain")}
              </button>
            )}
            {!creating && (
              <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
                {t("workflowEvents.add")}
              </button>
            )}
          </div>
        )}
      </div>
      {addingDomain && (
        <DomainForm
          target={target}
          onAdded={(domain) => {
            setAddingDomain(false);
            setAdded(domain.name);
          }}
          onCancel={() => setAddingDomain(false)}
        />
      )}
      {added !== null && (
        <p className="notice" role="status">
          {t("dataModels.domainForm.added", { name: added })}
        </p>
      )}
      {creating && (
        <DeclareForm
          target={target}
          perimeter={scope}
          onDeclared={() => setCreating(false)}
          onCancel={() => setCreating(false)}
        />
      )}
      {perimeters.isPending && (
        <p className="muted" role="status">
          {t("dataModels.loading")}
        </p>
      )}
      {perimeters.isError && <ModelRefusal error={perimeters.error} />}
      {/* Un périmètre nommé que la branche ne porte pas : un domaine supprimé, ou une vue
          partagée après coup. On le DIT, plutôt que de rendre une page vide qui se lirait
          comme « ce périmètre ne déclare rien ». */}
      {perimeters.isSuccess && scope !== undefined && shown.length === 0 && (
        <p className="muted">{t("workflowEvents.perimeter.unknown", { name: scope })}</p>
      )}
      {shown.map((perimeter) => (
        <PerimeterSection
          key={perimeter.scope}
          target={target}
          perimeter={perimeter}
          onOpenModel={onOpenModel}
        />
      ))}
    </section>
  );
}
