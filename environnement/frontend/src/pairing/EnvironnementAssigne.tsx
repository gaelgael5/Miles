import { useTranslation } from "react-i18next";

import { useAssignedEnvironment } from "../api/environment";

/**
 * L'environnement du référentiel auquel le module d'enrôlement nous a rattachés.
 *
 * Ce module ne CHOISIT pas son environnement : la décision est prise par un humain chez
 * l'enrôlement, qui est l'autorité unique sur l'affectation des devices. Cet écran la lit
 * et l'affiche, et il n'existe aucun geste ici pour la changer.
 *
 * Quatre cas, et les quatre se lisent différemment — c'est pourquoi `fresh` est porté par
 * la réponse au lieu d'être déduit de la présence d'une valeur :
 *
 * - frais avec valeur : ce que le pair vient de dire ;
 * - frais SANS valeur : le pair répond qu'aucun environnement ne nous est rattaché ;
 * - pas frais avec valeur : la dernière valeur connue, SA DATE, et le fait qu'elle n'a pas
 *   pu être rafraîchie. Un repli qui ne se dit pas est indiscernable d'un bug ;
 * - pas frais SANS valeur : on le dit, plutôt que de montrer un vide qui se lirait
 *   « aucun environnement rattaché » à un administrateur dont le réseau est coupé.
 */
export function EnvironnementAssigne() {
  const { t } = useTranslation();
  const assigne = useAssignedEnvironment();

  if (assigne.isPending) {
    return <p role="status">{t("assignedEnvironment.loading")}</p>;
  }
  if (assigne.data === undefined) {
    return (
      <p className="alert" role="status">
        {t("assignedEnvironment.unavailable")}
      </p>
    );
  }

  const { environment, fresh } = assigne.data;
  if (environment === null) {
    return (
      <p className="alert" role="status">
        {fresh ? t("assignedEnvironment.none") : t("assignedEnvironment.neverKnown")}
      </p>
    );
  }

  return (
    <div className="panel">
      <dl className="facts">
        <div>
          <dt className="caption">{t("assignedEnvironment.caption")}</dt>
          <dd className="value">
            {environment.label}
            {/* Le slug sous le libellé : c'est lui qui s'écrit dans une procédure, et le
                retrouver sans changer d'écran évite de le recopier de mémoire. */}
            <div className="row-sub">{environment.slug}</div>
          </dd>
        </div>
      </dl>
      <p className="help">{t("assignedEnvironment.help")}</p>
      {!fresh && (
        <p className="alert alert-warning" role="status">
          {t("assignedEnvironment.stale", {
            date: new Date(environment.fetched_at).toLocaleString(),
          })}
        </p>
      )}
    </div>
  );
}
