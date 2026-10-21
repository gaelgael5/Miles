import type { TFunction } from "i18next";

import { ApiError } from "./http";
import type { AccessReport } from "./workspaces";

/** Un workspace perdrait un droit : le changement n'a pas été appliqué. */
export interface DependentFailure {
  code: "acces_insuffisant";
  workspace: string;
  right: string | null;
  reason: string | null;
  report: AccessReport;
}

function detailOf(error: unknown, status: number): Record<string, unknown> | null {
  if (error instanceof ApiError && error.status === status && typeof error.detail === "object") {
    return error.detail as Record<string, unknown>;
  }
  return null;
}

export function dependentFailure(error: unknown): DependentFailure | null {
  const detail = detailOf(error, 422);
  return detail?.code === "acces_insuffisant" ? (detail as unknown as DependentFailure) : null;
}

/** Qui se sert encore de l'objet qu'on voulait supprimer, ou null. */
export function usedBy(error: unknown): string[] | null {
  const detail = detailOf(error, 409);
  return detail?.code === "utilise" ? (detail.by as string[]) : null;
}

/** Message d'un refus du menu `ns` (« certificates » ou « gitConnections »). */
export function errorMessage(t: TFunction, ns: string, error: unknown): string {
  const detail = detailOf(error, 422);
  if (detail && typeof detail.field === "string") {
    const reason = typeof detail.reason === "string" ? detail.reason : null;
    return t(reason ? `${ns}.errors.reasons.${reason}` : `${ns}.errors.invalid.${detail.field}`);
  }
  const failure = dependentFailure(error);
  if (failure) {
    const reason = t(`workspaces.reasons.${failure.reason ?? "echec"}`);
    return t(`${ns}.errors.access`, { workspace: failure.workspace, reason });
  }
  if (detail?.code === "depot_hors_adresse") {
    return t(`${ns}.errors.outside`, { workspace: String(detail.workspace) });
  }
  if (error instanceof ApiError && error.status === 409 && typeof error.detail === "string") {
    return t(`${ns}.errors.conflict.${error.detail}`);
  }
  return t(`${ns}.errors.unexpected`);
}
