import type { JsonSchema } from "jsonjoy-builder";
import { useTranslation } from "react-i18next";

import type { WorkTarget } from "../api/workTarget";
import { useEventSocle } from "../api/workflowEvents";
import LockedSchema from "../dataModels/LockedSchema";

/**
 * L'EVENT DE BASE, en tête du référentiel et en lecture seule.
 *
 * Gael, le 19/11/2026 : « tout d'abord je veux voir au départ l'event de base. celui qui
 * est dans le bloc urban-workflow. il est présent sur le disque et dans les menus en
 * lecture seul. » C'est de lui que dérive tout type d'event : le moteur applique sa racine
 * à TOUT payload, qu'un renvoi soit écrit ou non.
 *
 * Servi par le portail depuis le moteur installé, et non posé dans le dépôt du workspace
 * (décision 2 du 22/11/2026) : une copie versionnée avec le paramétrage serait une seconde
 * source, qui dérive à la première montée de version du moteur, pour un fichier que
 * personne n'édite.
 *
 * Montré dans le MÊME éditeur visuel que les champs métier, verrouillé : montré autrement,
 * il se lirait comme une annexe et on ne verrait plus qu'un event en DÉRIVE (relevé par
 * Gael le 11/11/2026). Aucun geste ne l'édite, ne le renomme ni ne le supprime — il n'y a
 * pas de bouton grisé, il n'y a pas de bouton.
 */
export function BaseEvent({ target }: { target: WorkTarget }) {
  const { t } = useTranslation();
  const socle = useEventSocle(target);

  return (
    <section className="card" aria-label={t("workflowEvents.base.title")}>
      <div className="page-head">
        <div>
          <h2>{t("workflowEvents.base.title")}</h2>
          <p className="help">{t("workflowEvents.base.help")}</p>
        </div>
        <span className="badge">{t("workflowEvents.base.readOnly")}</span>
      </div>
      {socle.isPending && (
        <p className="muted" role="status">
          {t("dataModels.loading")}
        </p>
      )}
      {socle.data !== undefined && <LockedSchema schema={socle.data as JsonSchema} />}
    </section>
  );
}
