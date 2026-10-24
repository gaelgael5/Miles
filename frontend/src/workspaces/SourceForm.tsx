import { type FormEvent, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { useChains } from "../api/chains";
import { proposeSlug } from "../api/contracts";
import type { Source, SourceProblem } from "../api/sources";
import { useStorages } from "../api/storages";
import type { WorkTarget } from "../api/workTarget";

export const EMPTY_SOURCE: Source = {
  name: "",
  label: "",
  storage: "",
  split: "",
  chain: "",
  large_file: false,
  unified_transaction: false,
};

/**
 * Formulaire d'une source, en déclaration comme en modification. Le nom est figé une fois
 * déclaré : c'est l'identité de la source, et le fichier `sources/<nom>.yaml` le porte.
 *
 * Révisé le 24/10/2026 (844f15ad) : la source ne déclare plus ce qui est stocké — elle
 * CHOISIT un storage, qui porte le modèle, la clé et les propriétés indexables.
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
  const storages = useStorages(target);
  const chains = useChains(target);
  // Semé une fois : l'écran est remonté (clé) quand la source affichée change.
  const [source, setSource] = useState<Source>(initial);
  // L'identifiant suit le libellé tant qu'on ne l'a pas touché ; modifiable à la création
  // seulement, il est figé ensuite — même geste que les contrats, chaînes et storages.
  const [name, setName] = useState<string | null>(creating ? null : initial.name);
  const set = (change: Partial<Source>) => setSource((current) => ({ ...current, ...change }));
  const shownName = name ?? proposeSlug(source.label);

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit({ ...source, name: shownName });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={submitLabel}>
      {/* Sur la racine, la déclaration se lit sans se modifier : champs désactivés d'un coup. */}
      <fieldset className="plain-fieldset" disabled={target.readOnly}>
        <label className="field">
          {t("sources.fields.label")}
          <input required value={source.label} onChange={(e) => set({ label: e.target.value })} />
        </label>
        <label className="field">
          {t("sources.fields.name")}
          <input
            required
            disabled={!creating}
            value={shownName}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <p className="help">{t("sources.form.nameHelp")}</p>
        <label className="field">
          {t("sources.fields.storage")}
          <select required value={source.storage} onChange={(e) => set({ storage: e.target.value })}>
            <option value="">{t("sources.form.choose")}</option>
            {(storages.data ?? []).map((s) => (
              <option key={s.name} value={s.name}>
                {s.name}
                {s.model === null ? "" : ` (${s.model})`}
              </option>
            ))}
          </select>
        </label>
        <p className="help">{t("sources.form.storageHelp")}</p>
        <label className="field">
          {t("sources.fields.split")}
          <input
            required
            className="mono"
            value={source.split}
            onChange={(e) => set({ split: e.target.value })}
          />
        </label>
        <p className="help">{t("sources.form.splitHelp")}</p>
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
          <input
            type="checkbox"
            checked={source.large_file}
            onChange={(e) => set({ large_file: e.target.checked })}
          />
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
