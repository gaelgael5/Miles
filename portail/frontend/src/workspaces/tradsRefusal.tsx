import { useTranslation } from "react-i18next";

import { ApiError } from "@miles/socle-web";

export function errorKey(error: unknown): string {
  if (error instanceof ApiError && error.status === 422) {
    const detail = error.detail as { code?: string; field?: string } | undefined;
    if (detail?.code === "trads_illisible") {
      return "trads.errors.unreadable";
    }
    if (detail?.field === "name") {
      return "trads.errors.invalidName";
    }
    if (detail?.field === "label") {
      return "trads.errors.invalidLabel";
    }
  }
  if (error instanceof ApiError && error.status === 409) {
    const detail = error.detail;
    if (typeof detail === "string") {
      return `trads.errors.${detail}`;
    }
  }
  return "trads.errors.unexpected";
}

export function Refusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (error instanceof ApiError && error.status === 409) {
    const detail = error.detail as { code?: string; label?: string } | undefined;
    if (detail?.code === "contexte_pris") {
      return (
        <p className="alert" role="alert">
          {t("trads.errors.taken", { label: detail.label })}
        </p>
      );
    }
  }
  const path =
    error instanceof ApiError && error.status === 422
      ? ((error.detail as { path?: string } | undefined)?.path ?? "")
      : "";
  return (
    <p className="alert" role="alert">
      {t(errorKey(error), { path })}
    </p>
  );
}
