import { useTranslation } from "react-i18next";

import { ApiError } from "@miles/socle-web";
import type { ModelProblem } from "../api/dataModels";

type Detail = {
  code?: string;
  field?: string;
  reason?: string;
  line?: number | null;
  column?: number | null;
  message?: string;
  problems?: ModelProblem[];
  by?: string[];
};

/** Un manquement de l'artefact de déclaration : positionné, comme le moteur le positionne. */
type DslProblem = { line: number; column: number; message: string };

function detailOf(error: unknown): Detail | null {
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail !== null) {
    return error.detail as Detail;
  }
  return null;
}

/** Message d'un refus ; les manquements à la grammaire s'affichent à part, un par ligne. */
function errorKey(error: unknown, fields: Record<string, string>): [string, Record<string, string>] {
  const detail = detailOf(error);
  if (detail?.code === "yaml_invalide") {
    const at = { line: String(detail.line ?? "?"), column: String(detail.column ?? "?") };
    return ["dataModels.errors.syntax", { ...at, message: detail.message ?? "" }];
  }
  if (detail?.code === "artefact_illisible") {
    return ["workflowEvents.errors.artefact", {}];
  }
  if (detail?.code === "modele_non_conforme") {
    return ["dataModels.errors.grammar", {}];
  }
  // Le modèle DÉSIGNÉ par une déclaration ne peut pas porter un event : le message de
  // tête dit laquelle des deux familles est refusée, et les manquements s'affichent
  // dessous par le même chemin.
  if (detail?.code === "declaration_non_conforme") {
    return ["workflowEvents.errors.grammar", {}];
  }
  if (detail?.code === "utilise") {
    return ["dataModels.errors.inUse", { list: (detail.by ?? []).join(", ") }];
  }
  if (detail?.code === "acces_depot") {
    return ["dataModels.errors.access", { reason: detail.reason ?? "echec" }];
  }
  if (detail?.field) {
    return [fields[detail.field] ?? `dataModels.errors.invalid.${detail.field}`, {}];
  }
  if (error instanceof ApiError && typeof error.detail === "string") {
    return [`dataModels.errors.conflict.${error.detail}`, {}];
  }
  return ["dataModels.errors.unexpected", {}];
}

/**
 * Refus d'une écriture de modèle : le message, puis chaque écart à sa place. `fields`
 * redit un champ refusé quand le même nom ne désigne pas la même chose (le `name` d'un
 * domaine n'est pas le slug d'un modèle).
 */
export function ModelRefusal({
  error,
  fields = {},
}: {
  error: unknown;
  fields?: Record<string, string>;
}) {
  const { t } = useTranslation();
  const detail = detailOf(error);
  const [key, values] = errorKey(error, fields);
  const problems = detail?.problems ?? [];
  // L'artefact de déclaration n'est pas un YAML : ses manquements portent une position du
  // moteur, pas un chemin de propriété. Les faire passer par la liste ci-dessous
  // afficherait « undefined — » pour chacun.
  const dsl = detail?.code === "artefact_illisible" ? (problems as unknown as DslProblem[]) : [];
  return (
    <div className="alert" role="alert">
      <p>{t(key, values)}</p>
      {dsl.length > 0 && (
        <ul>
          {dsl.map((p) => (
            <li key={`${p.line}-${p.column}-${p.message}`}>
              {t("workflowEvents.errors.at", { line: p.line, column: p.column })} — {p.message}
            </li>
          ))}
        </ul>
      )}
      {dsl.length === 0 && problems.length > 0 && (
        <ul>
          {problems.map((p) => (
            <li key={`${p.path}-${p.code}`}>
              <span className="mono">{p.path || "/"}</span> —{" "}
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
      )}
    </div>
  );
}
