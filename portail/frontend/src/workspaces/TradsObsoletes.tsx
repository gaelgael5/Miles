import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import { type TradsContext, useCleanObsoleteCulture } from "../api/trads";
import type { WorkTarget } from "../api/workTarget";
import { Refusal } from "./tradsRefusal";

/**
 * Les cultures que le workspace ne retient plus, mais dont le dépôt garde les fichiers.
 *
 * Retirer une culture ne détruit rien — on ne détruit pas un travail de traduction en
 * décochant une case —, mais rien ne permettait ensuite de faire le ménage. Ce n'est pas
 * une erreur : ces fichiers reviennent si la culture est remise, et le bloc le dit avant
 * de proposer de les enlever.
 */
export function Obsoletes({
  target,
  context,
  readOnly,
}: {
  target: WorkTarget;
  context: TradsContext;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  const clean = useCleanObsoleteCulture(target);
  const [confirming, setConfirming] = useState<string | null>(null);
  const cultures = Object.entries(context.obsolete);
  if (cultures.length === 0) {
    return null;
  }
  const values = confirming === null ? 0 : (context.obsolete[confirming] ?? 0);
  return (
    <div className="cell">
      <div className="caption">{t("trads.obsolete.caption")}</div>
      <div className="value">
        {cultures.map(([culture, count]) => (
          <span key={culture}>
            <span className="badge">{t("trads.obsolete.badge", { culture, count })}</span>
            {!readOnly && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setConfirming(culture)}
              >
                {t("trads.obsolete.clean")}
              </button>
            )}
          </span>
        ))}
      </div>
      {clean.isError && <Refusal error={clean.error} />}
      {confirming !== null && (
        <ConfirmDialog
          title={t("trads.obsolete.title", { culture: confirming })}
          confirmLabel={t("trads.obsolete.clean")}
          cancelLabel={t("trads.form.cancel")}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            clean.mutate({ context: context.name, culture: confirming });
            setConfirming(null);
          }}
        >
          {/* Le nombre de valeurs AVANT de les détruire : c'est la seule chose qui rende
              ce geste décidable, comme pour la suppression d'un contexte. */}
          <p className="alert">
            {t("trads.obsolete.confirm", { culture: confirming, count: values })}
          </p>
          <p className="muted">{t("trads.remove.revertible")}</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
