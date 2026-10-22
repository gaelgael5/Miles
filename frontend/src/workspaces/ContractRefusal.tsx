import { useTranslation } from "react-i18next";

import { ApiError } from "../api/http";

type Detail = {
  code?: string;
  field?: string;
  reason?: string;
  line?: number | null;
  column?: number | null;
  message?: string;
  found?: string | null;
  accepted?: string[];
  by?: string;
  problems?: { path: string; message: string }[];
  status?: number;
};

export function ContractRefusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const detail =
    error instanceof ApiError && typeof error.detail === "object" ? (error.detail as Detail) : null;
  let message = t("contracts.errors.unexpected");
  if (detail?.code === "openapi_illisible") {
    message = t("contracts.errors.unreadable", {
      line: String(detail.line ?? "?"),
      column: String(detail.column ?? "?"),
      message: detail.message ?? "",
    });
  } else if (detail?.code === "openapi_invalide") {
    message = t("contracts.errors.invalid");
  } else if (detail?.code === "version_non_prise_en_charge") {
    message = t("contracts.errors.version", {
      found: detail.found ?? "—",
      accepted: (detail.accepted ?? []).join(", "),
    });
  } else if (detail?.code === "lecture_distante") {
    message = t(`contracts.errors.remote.${detail.reason ?? "injoignable"}`, {
      status: String(detail.status ?? "?"),
    });
  } else if (detail?.code === "slug_pris") {
    message = t("contracts.errors.taken", { by: detail.by ?? "" });
  } else if (detail?.code === "acces_depot") {
    message = t("dataModels.errors.access", { reason: detail.reason ?? "echec" });
  } else if (detail?.field) {
    message = t(`contracts.errors.field.${detail.field}${detail.reason ? `_${detail.reason}` : ""}`);
  } else if (error instanceof ApiError && typeof error.detail === "string") {
    message = t(`dataModels.errors.conflict.${error.detail}`);
  }
  return (
    <div className="alert" role="alert">
      <p>{message}</p>
      {detail?.problems && (
        <ul>
          {detail.problems.map((p) => (
            <li key={`${p.path}-${p.message}`}>
              <span className="mono">{p.path}</span> — {p.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
