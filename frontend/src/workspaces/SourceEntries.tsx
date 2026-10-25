import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useChains } from "../api/chains";
import { useDataModels } from "../api/dataModels";
import { MAX_BATCH, type SourceEntry } from "../api/sources";
import type { WorkTarget } from "../api/workTarget";

/** Les types d'entrée proposés. Un seul instruit à ce jour, nommé plutôt que sous-entendu. */
const KINDS = ["web"];

export function emptyEntry(kind: string): SourceEntry {
  return {
    kind,
    source_model: "",
    chain: "",
    // Aucun mode coché : l'entrée se refuse tant qu'on n'a pas dit ce qu'elle expose.
    modes: { element: false, batch: false, file: false },
    split: "",
    unified_transaction: false,
    // 1 : on écrit ce qu'on vient de lire. Le comportement le plus sûr par défaut.
    write_batch: 1,
  };
}

function EntryCard({
  target,
  entry,
  rank,
  disabled,
  onChange,
  onRemove,
}: {
  target: WorkTarget;
  entry: SourceEntry;
  rank: number;
  disabled: boolean;
  onChange: (entry: SourceEntry) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const models = useDataModels(target);
  const chains = useChains(target);
  const set = (change: Partial<SourceEntry>) => onChange({ ...entry, ...change });
  const mode = (change: Partial<SourceEntry["modes"]>) =>
    set({ modes: { ...entry.modes, ...change } });

  return (
    <li className="entry-card">
      <h3>{t(`sources.kinds.${entry.kind}`, { defaultValue: entry.kind })}</h3>
      <label className="field">
        {t("sources.fields.entrySourceModel", { rank: rank + 1 })}
        <select
          required
          disabled={disabled}
          value={entry.source_model}
          onChange={(e) => set({ source_model: e.target.value })}
        >
          <option value="">{t("sources.form.choose")}</option>
          {(models.data ?? []).map((m) => (
            <option key={`${m.scope}/${m.name}`} value={`${m.scope}/${m.name}`}>
              {m.scope}/{m.name}
            </option>
          ))}
        </select>
      </label>
      <p className="help">{t("sources.form.entrySourceModelHelp")}</p>
      <label className="field">
        {t("sources.fields.entryChain", { rank: rank + 1 })}
        <select
          required
          disabled={disabled}
          value={entry.chain}
          onChange={(e) => set({ chain: e.target.value })}
        >
          <option value="">{t("sources.form.choose")}</option>
          {(chains.data ?? []).map((c) => (
            <option key={c.slug} value={c.slug}>
              {c.label ?? c.slug} ({c.slug})
            </option>
          ))}
        </select>
      </label>
      <p className="help">{t("sources.form.entryChainHelp")}</p>
      <fieldset className="picker-field">
        <legend>{t("sources.fields.modes")}</legend>
        <p className="help">{t("sources.form.modesHelp")}</p>
        <label className="field-check">
          <input
            type="checkbox"
            disabled={disabled}
            checked={entry.modes.element}
            onChange={(e) => mode({ element: e.target.checked })}
          />
          {t("sources.modes.element")}
        </label>
        <label className="field-check">
          <input
            type="checkbox"
            disabled={disabled}
            checked={entry.modes.batch}
            onChange={(e) => mode({ batch: e.target.checked })}
          />
          {t("sources.modes.batch", { max: MAX_BATCH })}
        </label>
        <label className="field-check">
          <input
            type="checkbox"
            disabled={disabled}
            checked={entry.modes.file}
            onChange={(e) => mode({ file: e.target.checked })}
          />
          {t("sources.modes.file")}
        </label>
      </fieldset>
      {/* Le découpage ne s'affiche qu'avec le mode qui l'exige : hors de lui, demander un
          chemin qui ne sert à rien se paie en déclarations fausses. */}
      {entry.modes.file && (
        <>
          <label className="field">
            {t("sources.fields.entrySplit", { rank: rank + 1 })}
            <input
              required
              className="mono"
              disabled={disabled}
              value={entry.split}
              onChange={(e) => set({ split: e.target.value })}
            />
          </label>
          <p className="help">{t("sources.form.splitHelp")}</p>
        </>
      )}
      <label className="field-check">
        <input
          type="checkbox"
          disabled={disabled}
          checked={entry.unified_transaction}
          onChange={(e) => set({ unified_transaction: e.target.checked })}
        />
        {t("sources.fields.unifiedTransaction")}
      </label>
      <label className="field">
        {t("sources.fields.writeBatch", { rank: rank + 1 })}
        <input
          required
          type="number"
          min={1}
          step={1}
          disabled={disabled}
          value={entry.write_batch}
          // Un champ nombre rend "" quand on efface : on garde 1 plutôt que NaN, que le
          // contrat d'entrée refuserait avec un message qui ne dirait pas quoi faire.
          onChange={(e) => set({ write_batch: Number(e.target.value) || 1 })}
        />
      </label>
      <p className="help">{t("sources.form.writeBatchHelp")}</p>
      {!disabled && (
        <div className="actions">
          <button type="button" className="btn btn-secondary" onClick={onRemove}>
            {t("sources.form.removeEntry", { rank: rank + 1 })}
          </button>
        </div>
      )}
    </li>
  );
}

/**
 * Les entrées d'une source (Gael, 25/10/2026) : « on a un bouton ajouter une source. on
 * clique puis on choisit entrée web ». Le type se choisit AVANT le reste, parce que c'est
 * lui qui dit quels réglages ont un sens.
 */
export function SourceEntries({
  target,
  entries,
  disabled,
  onChange,
}: {
  target: WorkTarget;
  entries: SourceEntry[];
  disabled: boolean;
  onChange: (entries: SourceEntry[]) => void;
}) {
  const { t } = useTranslation();
  const [choosing, setChoosing] = useState(false);

  return (
    <section aria-labelledby="source-entries">
      <h2 id="source-entries">{t("sources.entries.title")}</h2>
      {entries.length === 0 && <p className="muted">{t("sources.entries.empty")}</p>}
      <ul className="plain-list">
        {entries.map((entry, rank) => (
          <EntryCard
            key={rank}
            target={target}
            entry={entry}
            rank={rank}
            disabled={disabled}
            onChange={(changed) => onChange(entries.map((e, i) => (i === rank ? changed : e)))}
            onRemove={() => onChange(entries.filter((_, i) => i !== rank))}
          />
        ))}
      </ul>
      {!disabled && !choosing && (
        <button type="button" className="btn btn-secondary" onClick={() => setChoosing(true)}>
          {t("sources.entries.add")}
        </button>
      )}
      {!disabled && choosing && (
        <div className="card">
          <p className="caption">{t("sources.entries.chooseKind")}</p>
          <div className="actions">
            {KINDS.map((kind) => (
              <button
                key={kind}
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  onChange([...entries, emptyEntry(kind)]);
                  setChoosing(false);
                }}
              >
                {t(`sources.kinds.${kind}`)}
              </button>
            ))}
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setChoosing(false)}
            >
              {t("dataModels.form.cancel")}
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
