import { useTranslation } from "react-i18next";

import type { ModelProblem } from "../api/dataModels";
import { ApiError } from "../api/http";

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

function detailOf(error: unknown): Detail | null {
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail !== null) {
    return error.detail as Detail;
  }
  return null;
}

/** Message d'un refus ; les manquements à la grammaire s'affichent à part, un par ligne. */
function errorKey(error: unknown): [string, Record<string, string>] {
  const detail = detailOf(error);
  if (detail?.code === "yaml_invalide") {
    const at = { line: String(detail.line ?? "?"), column: String(detail.column ?? "?") };
    return ["dataModels.errors.syntax", { ...at, message: detail.message ?? "" }];
  }
  if (detail?.code === "modele_non_conforme") {
    return ["dataModels.errors.grammar", {}];
  }
  if (detail?.code === "utilise") {
    return ["dataModels.errors.inUse", { list: (detail.by ?? []).join(", ") }];
  }
  if (detail?.code === "acces_depot") {
    return ["dataModels.errors.access", { reason: detail.reason ?? "echec" }];
  }
  if (detail?.field) {
    return [`dataModels.errors.invalid.${detail.field}`, {}];
  }
  if (error instanceof ApiError && typeof error.detail === "string") {
    return [`dataModels.errors.conflict.${error.detail}`, {}];
  }
  return ["dataModels.errors.unexpected", {}];
}

/** Refus d'une écriture de modèle : le message, puis chaque écart à sa place. */
export function ModelRefusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const [key, values] = errorKey(error);
  const problems = detailOf(error)?.problems ?? [];
  return (
    <div className="alert" role="alert">
      <p>{t(key, values)}</p>
      {problems.length > 0 && (
        <ul>
          {problems.map((p) => (
            <li key={`${p.path}-${p.code}`}>
              <span className="mono">{p.path || "/"}</span> —{" "}
              {t(`dataModels.problems.${p.code}`, { detail: p.detail ?? "" })}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
