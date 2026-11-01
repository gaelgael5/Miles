import { useTranslation } from "react-i18next";

import type { FileReport } from "../api/dataModels";

/**
 * Ce qui ne passe pas les règles, fichier par fichier.
 *
 * Dans son fichier depuis le 01/11/2026, parce qu'il y a désormais DEUX moments où ces
 * rapports s'affichent : à l'ouverture de l'écran, et dans le refus d'un enregistrement.
 * Gael : « il faudrait que le message d'erreur arrive avant que j'aie envie de commiter ».
 * Deux rendus auraient divergé, et l'un des deux aurait fini par dire les choses moins
 * bien que l'autre — or c'est sur ces lignes qu'on décide quoi corriger.
 */
export function ProblemReports({ reports }: { reports: FileReport[] }) {
  const { t } = useTranslation();
  return (
    <>
      {reports.map((report) => (
        <div key={report.path}>
          <p className="mono">{report.path || t("versions.tree")}</p>
          <ul>
            {report.problems.map((p) => (
              <li key={`${p.path}-${p.code}`}>
                {p.path && <span className="mono">{p.path} — </span>}
                {t(`dataModels.problems.${p.code}`, {
                  detail: p.detail ?? "",
                  // Un code sans libellé affichait sa CLEF BRUTE — relevé par Gael sur
                  // une copie d'écran le 01/11/2026. Le repli dit le code et son détail,
                  // ce qui reste diagnosticable ; la clef, non. La garde du backend
                  // (`test_problem_labels.py`) empêche d'en arriver là, et ce repli est
                  // ce qui se passe si elle est un jour contournée.
                  defaultValue: t("dataModels.problems._sans_message", {
                    code: p.code,
                    detail: p.detail ? ` (${p.detail})` : "",
                  }),
                })}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </>
  );
}
