import { useTranslation } from "react-i18next";

import type { WorkTarget } from "../api/workTarget";
import { useEventPerimeters } from "../api/workflowEvents";
import { perimeterLabel } from "../events/PerimeterSection";

/**
 * Les périmètres sous « Types d'event » (Gael, 12/11/2026) : « on a des sous-menus qui
 * permettent quand on clique sur le lien de lire les différents fichier d'artefacts pour
 * afficher les referentiels ».
 *
 * Les périmètres, et non les types : un type s'ouvre dans le référentiel de son
 * périmètre, et lister tous les types ici referait la page dans le menu. Lus seulement
 * quand la branche est dépliée — chaque lecture clone la branche.
 *
 * Un périmètre dont l'artefact ne se relit pas RESTE dans la liste, avec sa pastille :
 * c'est l'écran qui dit pourquoi, et le faire disparaître du menu le rendrait
 * inatteignable au moment précis où il faut aller le réparer (critère 5).
 */
export function EventPerimeterLinks({
  target,
  open,
  current,
  onSelect,
}: {
  target: WorkTarget;
  open: boolean;
  current: string | undefined;
  onSelect: (scope: string) => void;
}) {
  const { t } = useTranslation();
  const perimeters = useEventPerimeters(target, open);
  return (
    <>
      {perimeters.data?.map((perimeter) => (
        <button
          key={perimeter.scope}
          type="button"
          className="sidebar-link sidebar-subsublink"
          aria-current={current === perimeter.scope ? "page" : undefined}
          onClick={() => onSelect(perimeter.scope)}
        >
          {perimeterLabel(t, perimeter.scope)}
          {perimeter.problems.length > 0 && (
            <span className="badge badge-danger">{t("workflowEvents.perimeter.badge")}</span>
          )}
        </button>
      ))}
    </>
  );
}
