import { useTranslation } from "react-i18next";

import type { Access, Grant } from "../api/apiKeys";
import { useWorkspaces } from "../api/workspaces";

/** Droits d'une clé, workspace par workspace : aucun par défaut, comme le serveur. */
export function GrantsEditor({ grants, onChange }: { grants: Grant[]; onChange: (grants: Grant[]) => void }) {
  const { t } = useTranslation();
  const workspaces = useWorkspaces();
  const accessOf = (id: string) => grants.find((g) => g.workspace_id === id)?.access ?? "";

  function set(id: string, access: Access | "") {
    const others = grants.filter((g) => g.workspace_id !== id);
    onChange(access === "" ? others : [...others, { workspace_id: id, access }]);
  }

  return (
    <fieldset className="field">
      <legend>{t("apiKeys.fields.grants")}</legend>
      <p className="help">{t("apiKeys.form.grantsHelp")}</p>
      {(workspaces.data ?? []).map((w) => (
        <label key={w.id} className="field">
          {w.name} <span className="mono muted">{w.id}</span>
          <select value={accessOf(w.id)} onChange={(e) => set(w.id, e.target.value as Access | "")}>
            <option value="">{t("apiKeys.access.none")}</option>
            <option value="lecture">{t("apiKeys.access.lecture")}</option>
            <option value="ecriture">{t("apiKeys.access.ecriture")}</option>
          </select>
        </label>
      ))}
    </fieldset>
  );
}
