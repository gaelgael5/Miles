import { useTranslation } from "react-i18next";

import type { AccessReport } from "../api/workspaces";

/** Compte rendu des cinq droits : lequel a échoué, pourquoi, et ce qui reste à la main. */
export function AccessReportView({ report }: { report: AccessReport }) {
  const { t } = useTranslation();
  return (
    <div>
      <ul>
        {report.checks.map((check) => (
          <li key={check.right}>
            {t(`workspaces.rights.${check.right}`)} —{" "}
            {check.ok
              ? t("workspaces.check.ok")
              : t(`workspaces.reasons.${check.reason ?? "echec"}`)}
          </li>
        ))}
      </ul>
      {report.initialized_branch && (
        <p>{t("workspaces.check.initialized", { branch: report.initialized_branch })}</p>
      )}
      {report.existing_branches > 0 && (
        <p>{t("workspaces.check.existing", { count: report.existing_branches })}</p>
      )}
      {/* Jamais nettoyé en silence ni oublié : le nom exact, à supprimer à la main. */}
      {report.residual_branch && (
        <p role="alert">{t("workspaces.check.residualBranch", { name: report.residual_branch })}</p>
      )}
      {report.residual_tag && (
        <p role="alert">{t("workspaces.check.residualTag", { name: report.residual_tag })}</p>
      )}
    </div>
  );
}
