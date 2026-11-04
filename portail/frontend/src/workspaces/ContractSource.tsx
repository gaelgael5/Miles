import { type ChangeEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { useFetchContract } from "../api/contracts";
import type { WorkTarget } from "../api/workTarget";
import { ContractRefusal } from "./ContractRefusal";

/**
 * Deux façons d'amener le texte du contrat en plus du collage (Gael, 22/10/2026) : un
 * fichier du poste, ou une adresse que le back-office lit. Les deux remplissent la même
 * zone de texte : ce qui est importé est ce que l'administrateur a eu sous les yeux.
 */
export function ContractSource({
  target,
  onContent,
}: {
  target: WorkTarget;
  onContent: (content: string) => void;
}) {
  const { t } = useTranslation();
  const remote = useFetchContract(target);
  const [url, setUrl] = useState("");
  const [fileFailed, setFileFailed] = useState(false);

  function readFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file === undefined) {
      return;
    }
    setFileFailed(false);
    file.text().then(onContent, () => setFileFailed(true));
  }

  function fetchUrl() {
    remote.mutate(url, { onSuccess: (data) => onContent(data.content) });
  }

  return (
    <div className="panel">
      <label className="field">
        {t("contracts.source.file")}
        <input type="file" accept=".yaml,.yml,.json" onChange={readFile} />
      </label>
      {fileFailed && (
        <p className="alert" role="alert">
          {t("contracts.errors.file")}
        </p>
      )}
      <label className="field">
        {t("contracts.source.url")}
        <input
          type="url"
          inputMode="url"
          spellCheck={false}
          placeholder="https://"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
      </label>
      <p className="help">{t("contracts.source.urlHelp")}</p>
      <div className="actions">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={remote.isPending || url.trim() === ""}
          onClick={fetchUrl}
        >
          {t("contracts.source.fetch")}
        </button>
      </div>
      {remote.isError && <ContractRefusal error={remote.error} />}
    </div>
  );
}
