import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useCancelPairing, useConfirmPairing } from "../api/peering";
import { Refus } from "./Refus";

export function SaisieDuCode({ enrolmentUrl }: { enrolmentUrl: string }) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const confirmation = useConfirmPairing();
  const annulation = useCancelPairing();

  return (
    <div className="panel">
      <p className="help">{t("peering.pending.where", { url: enrolmentUrl })}</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          confirmation.mutate(code, { onSuccess: () => setCode("") });
        }}
      >
        <div className="field">
          <label htmlFor="pairing-code">{t("peering.pending.codeLabel")}</label>
          <input
            id="pairing-code"
            type="text"
            value={code}
            autoComplete="off"
            inputMode="numeric"
            onChange={(event) => setCode(event.target.value)}
          />
          {/* Le code arrive par copier-coller : espaces et retours à la ligne sont
              nettoyés avant l'envoi, pas refusés. */}
          <p className="help">{t("peering.pending.codeHelp")}</p>
        </div>
        {confirmation.isError && <Refus error={confirmation.error} />}
        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={confirmation.isPending}>
            {t("peering.pending.submit")}
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => annulation.mutate()}
          >
            {t("peering.pending.cancel")}
          </button>
        </div>
      </form>
    </div>
  );
}
