import { type FormEvent, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { useChains } from "../api/chains";
import { useDataModels } from "../api/dataModels";
import type { Filterable, Source, SourceProblem } from "../api/sources";
import type { WorkTarget } from "../api/workTarget";

export const EMPTY_SOURCE: Source = {
  name: "",
  model: "",
  split: "",
  keys: [],
  chain: "",
  large_file: false,
  unified_transaction: false,
  filterables: [],
};

function FilterablesEditor({
  rows,
  readOnly,
  onChange,
}: {
  rows: Filterable[];
  readOnly: boolean;
  onChange: (rows: Filterable[]) => void;
}) {
  const { t } = useTranslation();
  const set = (index: number, row: Filterable) => onChange(rows.map((r, i) => (i === index ? row : r)));
  return (
    <fieldset className="field">
      <legend>{t("sources.fields.filterables")}</legend>
      <p className="help">{t("sources.form.filterablesHelp")}</p>
      {rows.map((row, index) => (
        <div key={index} className="actions">
          <label className="field">
            {t("sources.fields.filterableName", { rank: index + 1 })}
            <input required value={row.name} onChange={(e) => set(index, { ...row, name: e.target.value })} />
          </label>
          <label className="field">
            {t("sources.fields.filterableJpath", { rank: index + 1 })}
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
              {t("sources.form.removeFilterable", { rank: index + 1 })}
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
          {t("sources.form.addFilterable")}
        </button>
      )}
    </fieldset>
  );
}

/**
 * Formulaire d'une source, en déclaration comme en modification. Le nom est figé une fois
 * déclaré : c'est l'identité de la source, et le fichier `sources/<nom>.yaml` le porte.
 */
export function SourceForm({
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
  initial: Source;
  creating: boolean;
  problems: SourceProblem[];
  pending: boolean;
  submitLabel: string;
  onSubmit: (source: Source) => void;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const models = useDataModels(target);
  const chains = useChains(target);
  // Semé une fois : l'écran est remonté (clé) quand la source affichée change.
  const [source, setSource] = useState<Source>(initial);
  const [keys, setKeys] = useState(initial.keys.join("\n"));
  const set = (change: Partial<Source>) => setSource((current) => ({ ...current, ...change }));

  function submit(event: FormEvent) {
    event.preventDefault();
    const lines = keys.split("\n").map((k) => k.trim()).filter((k) => k !== "");
    onSubmit({ ...source, keys: lines });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={submitLabel}>
      {/* Sur la racine, la déclaration se lit sans se modifier : champs désactivés d'un coup. */}
      <fieldset className="plain-fieldset" disabled={target.readOnly}>
      <label className="field">
        {t("sources.fields.name")}
        <input required disabled={!creating} value={source.name} onChange={(e) => set({ name: e.target.value })} />
      </label>
      <label className="field">
        {t("sources.fields.model")}
        <select required value={source.model} onChange={(e) => set({ model: e.target.value })}>
          <option value="">{t("sources.form.choose")}</option>
          {(models.data ?? []).map((m) => (
            <option key={`${m.scope}/${m.name}`} value={`${m.scope}/${m.name}`}>
              {m.scope}/{m.name}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        {t("sources.fields.split")}
        <input required className="mono" value={source.split} onChange={(e) => set({ split: e.target.value })} />
      </label>
      <p className="help">{t("sources.form.splitHelp")}</p>
      <label className="field">
        {t("sources.fields.keys")}
        <textarea required rows={2} className="mono" spellCheck={false} value={keys} onChange={(e) => setKeys(e.target.value)} />
      </label>
      <p className="help">{t("sources.form.keysHelp")}</p>
      <label className="field">
        {t("sources.fields.chain")}
        <select required value={source.chain} onChange={(e) => set({ chain: e.target.value })}>
          <option value="">{t("sources.form.choose")}</option>
          {(chains.data ?? []).map((c) => (
            <option key={c.slug} value={c.slug}>
              {c.label ?? c.slug} ({c.slug})
            </option>
          ))}
        </select>
      </label>
      <label className="field-check">
        <input type="checkbox" checked={source.large_file} onChange={(e) => set({ large_file: e.target.checked })} />
        {t("sources.fields.largeFile")}
      </label>
      <label className="field-check">
        <input
          type="checkbox"
          checked={source.unified_transaction}
          onChange={(e) => set({ unified_transaction: e.target.checked })}
        />
        {t("sources.fields.unifiedTransaction")}
      </label>
      <FilterablesEditor
        rows={source.filterables}
        readOnly={target.readOnly}
        onChange={(filterables) => set({ filterables })}
      />
      </fieldset>
      {problems.length > 0 && (
        <ul className="alert plain-list" role="alert">
          {problems.map((p, index) => (
            <li key={index}>
              <span className="mono">{p.path}</span> —{" "}
              {t(`sources.problems.${p.code}`, { defaultValue: p.code, detail: p.detail ?? "" })}
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
