import { useTranslation } from "react-i18next";

import { ApiError } from "@miles/socle-web";

type Detail = {
  code?: string;
  by?: string;
  workspace_id?: string;
  branch?: string;
  files?: string[];
};

/**
 * Le refus d'un geste de prise de main : il dit pourquoi, et NOMME qui ou quoi bloque.
 *
 * Dans son fichier depuis le 01/11/2026, comme `ContractRefusal` et `ModelRefusal` :
 * deuxième usage, le panneau des versions publie désormais lui aussi. Une seconde
 * écriture aurait traduit les mêmes codes autrement — et c'est précisément sur ces
 * messages que l'humain décide quoi faire.
 */
export function HoldRefusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  let message = t("holds.errors.unexpected");
  if (error instanceof ApiError && error.status === 409) {
    const detail = error.detail;
    if (typeof detail === "string") {
      message = t(`holds.errors.${detail}`, { defaultValue: t("holds.errors.unexpected") });
    } else if (typeof detail === "object" && detail !== null) {
      const { code, by, workspace_id, branch, files } = detail as Detail;
      message = t(`holds.errors.${code ?? "unexpected"}`, {
        by,
        workspace: workspace_id,
        branch,
        files: files?.join(", "),
      });
    }
  }
  return (
    <p className="alert" role="alert">
      {message}
    </p>
  );
}
