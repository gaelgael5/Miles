import { type FormEvent, type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import { proposeSlug } from "../api/contracts";
import { useDataModels } from "../api/dataModels";
import type { Indexable, Storage, StorageProblem } from "../api/storages";
import type { WorkTarget } from "../api/workTarget";
import { PathPicker, lastSegment } from "./ModelPathTree";

export const EMPTY_STORAGE: Storage = {
  name: "",
  label: "",
  model: "",
  keys: [],
  indexables: [],
};

/** Nom d'index proposé pour un chemin, jamais en doublon d'un existant. */
export function indexName(jpath: string, taken: string[]): string {
  // Un nom d'index fait au moins deux caractères (même règle que les autres noms) :
  // une propriété d'une lettre donnerait sinon une proposition refusée à l'enregistrement.
  const slug = proposeSlug(lastSegment(jpath));
  const base = slug.length < 2 ? "propriete" : slug;
  if (!taken.includes(base)) {
    return base;
  }
  // Un nom doublé serait refusé à l'enregistrement : on suffixe plutôt que de le laisser.
  for (let n = 2; n < 100; n += 1) {
    if (!taken.includes(`${base}-${n}`)) {
      return `${base}-${n}`;
    }
  }
  return base;
}

function IndexableRows({
  rows,
  disabled,
  onChange,
}: {
  rows: Indexable[];
  disabled: boolean;
  onChange: (rows: Indexable[]) => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return null;
  }
  return (
    <ul className="plain-list">
      {rows.map((row, index) => (
        <li key={row.jpath} className="actions">
          <label className="field">
            {t("storages.fields.indexableName", { rank: index + 1 })}
            <input
              required
              disabled={disabled}
              value={row.name}
              onChange={(e) =>
                onChange(rows.map((r, i) => (i === index ? { ...r, name: e.target.value } : r)))
              }
            />
          </label>
          {/* Le chemin vient de l'arbre : il s'affiche, il ne se tape plus. */}
          <span className="mono">{row.jpath}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Formulaire d'un storage, en déclaration comme en modification. Le nom est figé une fois
 * déclaré : c'est l'identité du storage, et le fichier `storages/<nom>.yaml` le porte.
 *
 * Clé et propriétés indexables se COCHENT dans l'arbre du modèle (Gael, 24/10/2026) : un
 * jpath tapé à la main se fait refuser après coup, pour une faute de frappe ou un tableau
 * traversé. L'arbre ne propose que ce que le modèle offre, et seulement des valeurs.
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
  // L'identifiant suit le libellé tant qu'on ne l'a pas touché ; modifiable à la création
  // seulement, il est figé ensuite — c'est le geste des contrats, des chaînes et des
  // modèles. Faire saisir le slug à la main revenait à refuser « Sites » sur sa majuscule.
  const [name, setName] = useState<string | null>(creating ? null : initial.name);
  const set = (change: Partial<Storage>) => setStorage((current) => ({ ...current, ...change }));
  const shownName = name ?? proposeSlug(storage.label);

  function toggleKey(path: string) {
    const keys = storage.keys.includes(path)
      ? storage.keys.filter((k) => k !== path)
      : [...storage.keys, path];
    set({ keys });
  }

  function toggleIndexable(path: string) {
    const rows = storage.indexables;
    const indexables = rows.some((i) => i.jpath === path)
      ? rows.filter((i) => i.jpath !== path)
      : [...rows, { name: indexName(path, rows.map((i) => i.name)), jpath: path }];
    set({ indexables });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit({ ...storage, name: shownName });
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
        <fieldset className="field">
          <legend>{t("storages.fields.keys")}</legend>
          <p className="help">{t("storages.form.keysHelp")}</p>
          <PathPicker
            target={target}
            model={storage.model}
            selected={storage.keys}
            disabled={target.readOnly}
            label={t("storages.fields.keys")}
            summary={
              storage.keys.length === 0 ? t("storages.form.noKey") : storage.keys.join(", ")
            }
            onToggle={toggleKey}
          />
        </fieldset>
        <fieldset className="field">
          <legend>{t("storages.fields.indexables")}</legend>
          <p className="help">{t("storages.form.indexablesHelp")}</p>
          <PathPicker
            target={target}
            model={storage.model}
            selected={storage.indexables.map((i) => i.jpath)}
            disabled={target.readOnly}
            label={t("storages.fields.indexables")}
            summary={
              storage.indexables.length === 0
                ? t("storages.form.noIndexable")
                : storage.indexables.map((i) => i.jpath).join(", ")
            }
            onToggle={toggleIndexable}
          />
          <IndexableRows
            rows={storage.indexables}
            disabled={target.readOnly}
            onChange={(indexables) => set({ indexables })}
          />
        </fieldset>
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
