import { type FormEvent, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { proposeSlug } from "../api/contracts";
import { useDataModels } from "../api/dataModels";
import type { Indexable, Storage, StorageProblem } from "../api/storages";
import type { WorkTarget } from "../api/workTarget";

export const EMPTY_STORAGE: Storage = { name: "", label: "", model: "", keys: [], indexables: [] };

function IndexablesEditor({
  rows,
  readOnly,
  onChange,
}: {
  rows: Indexable[];
  readOnly: boolean;
  onChange: (rows: Indexable[]) => void;
}) {
  const { t } = useTranslation();
  const set = (index: number, row: Indexable) =>
    onChange(rows.map((r, i) => (i === index ? row : r)));
  return (
    <fieldset className="field">
      <legend>{t("storages.fields.indexables")}</legend>
      <p className="help">{t("storages.form.indexablesHelp")}</p>
      {rows.map((row, index) => (
        <div key={index} className="actions">
          <label className="field">
            {t("storages.fields.indexableName", { rank: index + 1 })}
            <input
              required
              value={row.name}
              onChange={(e) => set(index, { ...row, name: e.target.value })}
            />
          </label>
          <label className="field">
            {t("storages.fields.indexableJpath", { rank: index + 1 })}
            <input
              required
              className="mono"
              value={row.jpath}
              onChange={(e) => set(index, { ...row, jpath: e.target.value })}
            />
          </label>
          {!readOnly && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => onChange(rows.filter((_, i) => i !== index))}
            >
              {t("storages.form.removeIndexable", { rank: index + 1 })}
            </button>
          )}
        </div>
      ))}
      {!readOnly && (
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => onChange([...rows, { name: "", jpath: "" }])}
        >
          {t("storages.form.addIndexable")}
        </button>
      )}
    </fieldset>
  );
}

/**
 * Formulaire d'un storage, en déclaration comme en modification. Le nom est figé une fois
 * déclaré : c'est l'identité du storage, et le fichier `storages/<nom>.yaml` le porte.
 */
export function StorageForm({
  target,
  initial,
  creating,
  problems,
  pending,
  submitLabel,
  onSubmit,
  children,
}: {
  target: WorkTarget;
  initial: Storage;
  creating: boolean;
  problems: StorageProblem[];
  pending: boolean;
  submitLabel: string;
  onSubmit: (storage: Storage) => void;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const models = useDataModels(target);
  // Semé une fois : l'écran est remonté (clé) quand le storage affiché change.
  const [storage, setStorage] = useState<Storage>(initial);
  const [keys, setKeys] = useState(initial.keys.join("\n"));
  // L'identifiant suit le libellé tant qu'on ne l'a pas touché ; modifiable à la création
  // seulement, il est figé ensuite — c'est le geste des contrats, des chaînes et des
  // modèles. Faire saisir le slug à la main revenait à refuser « Sites » sur sa majuscule.
  const [name, setName] = useState<string | null>(creating ? null : initial.name);
  const set = (change: Partial<Storage>) => setStorage((current) => ({ ...current, ...change }));
  const shownName = name ?? proposeSlug(storage.label);

  function submit(event: FormEvent) {
    event.preventDefault();
    const lines = keys
      .split("\n")
      .map((k) => k.trim())
      .filter((k) => k !== "");
    onSubmit({ ...storage, name: shownName, keys: lines });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={submitLabel}>
      {/* Sur la racine, la déclaration se lit sans se modifier : champs désactivés d'un coup. */}
      <fieldset className="plain-fieldset" disabled={target.readOnly}>
        <label className="field">
          {t("storages.fields.label")}
          <input required value={storage.label} onChange={(e) => set({ label: e.target.value })} />
        </label>
        <label className="field">
          {t("storages.fields.name")}
          <input
            required
            disabled={!creating}
            value={shownName}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <p className="help">{t("storages.form.nameHelp")}</p>
        <label className="field">
          {t("storages.fields.model")}
          <select required value={storage.model} onChange={(e) => set({ model: e.target.value })}>
            <option value="">{t("storages.form.choose")}</option>
            {(models.data ?? []).map((m) => (
              <option key={`${m.scope}/${m.name}`} value={`${m.scope}/${m.name}`}>
                {m.scope}/{m.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          {t("storages.fields.keys")}
          <textarea
            required
            rows={2}
            className="mono"
            spellCheck={false}
            value={keys}
            onChange={(e) => setKeys(e.target.value)}
          />
        </label>
        <p className="help">{t("storages.form.keysHelp")}</p>
        <IndexablesEditor
          rows={storage.indexables}
          readOnly={target.readOnly}
          onChange={(indexables) => set({ indexables })}
        />
      </fieldset>
      {problems.length > 0 && (
        <ul className="alert plain-list" role="alert">
          {problems.map((p, index) => (
            <li key={index}>
              <span className="mono">{p.path}</span> —{" "}
              {t(`storages.problems.${p.code}`, { defaultValue: p.code, detail: p.detail ?? "" })}
            </li>
          ))}
        </ul>
      )}
      {!target.readOnly && (
        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={pending}>
            {submitLabel}
          </button>
          {children}
        </div>
      )}
    </form>
  );
}
