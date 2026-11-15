import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import { useBranchLayout, useConvertLayout } from "../api/layout";
import type { WorkTarget } from "../api/workTarget";
import { refusalMessage } from "./refusalMessage";

/**
 * Ce qui bloque une branche entière, dit là où on le rencontre, avec le geste qui le lève.
 *
 * Le 15/11/2026, Gael ouvre « Types d'event » sur une branche à l'ancienne disposition :
 * l'écran refuse en nommant la conversion, qui n'existait que comme route HTTP. Un refus
 * qui nomme un geste qu'on ne peut pas faire est un cul-de-sac — même famille que le
 * marqueur de rubrique disparue corrigé la veille.
 *
 * Le bandeau est ICI, au-dessus de la vue refusée, et non sur l'écran des branches :
 * renvoyer ailleurs pour un clic est un détour que rien ne justifie (Gael, 01/11/2026,
 * à propos du bouton de publication).
 */
export function LayoutNotice({ target }: { target: WorkTarget }) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const layout = useBranchLayout(target);
  const convert = useConvertLayout(target);
  if (!layout.isSuccess || layout.data.refusal === null) {
    // Rien tant qu'on ne sait pas : un bandeau d'alerte affiché « au cas où » ferait
    // douter de branches saines.
    return null;
  }
  const { refusal, moves, event_types: types, conflicts } = layout.data;
  // La conversion refuserait aussi : on n'offre pas un bouton dont on connaît le refus.
  const offrable = refusal === "disposition_ancienne" && conflicts.length === 0;
  return (
    <div className="alert" role="alert">
      <p>{refusalMessage(t, `dataModels.errors.conflict.${refusal}`)}</p>
      {conflicts.length > 0 && (
        <p>{t("layout.notice.conflicts", { list: conflicts.join(", ") })}</p>
      )}
      {offrable && <p>{t("layout.notice.effect", { moves, types })}</p>}
      {offrable && target.canMigrate && (
        <button type="button" disabled={convert.isPending} onClick={() => setConfirming(true)}>
          {t("layout.notice.convert")}
        </button>
      )}
      {offrable && !target.canMigrate && (
        // Un bouton absent sans explication se lit comme une panne (Gael, 01/11/2026).
        <p className="muted">{t("layout.notice.holdRequired")}</p>
      )}
      {convert.isError && <p className="muted">{t("layout.notice.failed")}</p>}
      {confirming && (
        <ConfirmDialog
          title={t("layout.notice.confirmTitle")}
          confirmLabel={t("layout.notice.convert")}
          cancelLabel={t("dataModels.form.cancel")}
          onConfirm={() => {
            convert.mutate();
            setConfirming(false);
          }}
          onCancel={() => setConfirming(false)}
        >
          {t("layout.notice.confirmMessage", { branch: target.branch, moves })}
        </ConfirmDialog>
      )}
    </div>
  );
}
