import type { TFunction } from "i18next";

/**
 * Le message d'un refus désigné par une clef, avec un repli qui DIT LE CODE.
 *
 * Sans ce repli, un code de refus sans libellé s'affiche en CLEF BRUTE sur l'écran où
 * l'on décide quoi corriger : `dataModels.errors.conflict.disposition_ancienne`, relevé
 * par Gael sur une copie d'écran le 15/11/2026. C'est la même panne que celle du
 * 01/11/2026 une famille plus bas — les codes de problème —, et elle s'est reproduite
 * parce que la garde écrite ce jour-là ne couvrait que cette famille-là.
 *
 * La garde (`test_problem_labels.py`) reste ce qui empêche d'en arriver là ; ce repli est
 * ce qui se passe si elle est un jour contournée. Le code, lui, reste diagnosticable.
 */
export function refusalMessage(
  t: TFunction,
  key: string,
  values: Record<string, unknown> = {},
): string {
  return t(key, {
    ...values,
    defaultValue: t("dataModels.errors._sans_libelle", { code: key.split(".").pop() ?? key }),
  });
}
