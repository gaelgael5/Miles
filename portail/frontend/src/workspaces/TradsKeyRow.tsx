import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { TradsKey, ValueChanges } from "../api/tradsKeys";
import { type WorkspaceCultures, directionOf } from "../api/workspaceCultures";
import { ValueCell, ValueField } from "./ValueField";

/** Renommer un slug est une RUPTURE, pas une correction : son propre formulaire, averti. */
function RenameForm({
  slug,
  onDone,
  onRename,
}: {
  slug: string;
  onDone: () => void;
  onRename: (newSlug: string) => void;
}) {
  const { t } = useTranslation();
  const [next, setNext] = useState(slug);

  function submit(event: FormEvent) {
    event.preventDefault();
    onRename(next);
    onDone();
  }

  return (
    <form onSubmit={submit} aria-label={t("tradsKeys.rename.title", { slug })}>
      {/* L'avertissement AVANT le champ : il dit que le produit ne sait pas encore
          retrouver ce qui référence une clé, et c'est la seule raison d'hésiter. */}
      <p className="alert">{t("tradsKeys.rename.warning")}</p>
      <label className="field">
        {t("tradsKeys.fields.slug")}
        <input required value={next} onChange={(e) => setNext(e.target.value)} />
      </label>
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={next === slug}>
          {t("tradsKeys.rename.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDone}>
          {t("tradsKeys.form.cancel")}
        </button>
      </div>
    </form>
  );
}

/**
 * Une ligne de la table : le slug, puis une valeur par culture du workspace.
 *
 * L'édition s'ouvre à la demande plutôt que d'être toujours offerte : une table de
 * plusieurs milliers de clés ne monte pas autant de zones de saisie, et c'est le régime
 * normal au bout d'un an.
 */
export function TradsKeyRow({
  entry,
  columns,
  cultures,
  readOnly,
  pending,
  onSave,
  onRename,
  onRemove,
}: {
  entry: TradsKey;
  columns: string[];
  cultures: WorkspaceCultures | undefined;
  readOnly: boolean;
  pending: boolean;
  onSave: (values: ValueChanges) => void;
  onRename: (newSlug: string) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const defaultCulture = cultures?.default;

  function open() {
    setDraft(Object.fromEntries(columns.map((c) => [c, entry.values[c] ?? ""])));
    setEditing(true);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const changes: ValueChanges = {};
    for (const culture of columns) {
      const next = draft[culture] ?? "";
      const before = entry.values[culture] ?? "";
      if (next === before) {
        // Inchangée : la culture n'entre pas dans le corps, et son fichier n'est pas
        // réécrit. C'est ce qui garde le diff git lisible (critère 4).
        continue;
      }
      // Vidée : `null` retire la ligne du fichier plutôt que d'y laisser une valeur vide.
      changes[culture] = next === "" ? null : next;
    }
    onSave(changes);
    setEditing(false);
  }

  return (
    <li className="row trads-key-row">
      <div className="row-main">
        <code>{entry.slug}</code>
        {renaming && (
          <RenameForm slug={entry.slug} onDone={() => setRenaming(false)} onRename={onRename} />
        )}
      </div>
      {editing ? (
        <form
          className="trads-values"
          onSubmit={submit}
          aria-label={t("tradsKeys.edit.title", { slug: entry.slug })}
        >
          {columns.map((culture) => (
            <ValueField
              key={culture}
              culture={culture}
              direction={directionOf(cultures, culture)}
              value={draft[culture] ?? ""}
              required={culture === defaultCulture}
              onChange={(value) => setDraft((d) => ({ ...d, [culture]: value }))}
            />
          ))}
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={pending}>
              {t("tradsKeys.edit.submit")}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setEditing(false)}>
              {t("tradsKeys.form.cancel")}
            </button>
          </div>
        </form>
      ) : (
        <div className="trads-values">
          {columns.map((culture) => (
            // `cell` et non `field` : `.field` est fait pour un libellé SUIVI d'un champ
            // de saisie, et met tout son contenu en graisse 600 — en lecture, la valeur
            // sortait en gras et collée à son code de culture.
            <div className="cell" key={culture}>
              <div className="caption">{culture}</div>
              <div className="value">
                <ValueCell
                  culture={culture}
                  direction={directionOf(cultures, culture)}
                  value={entry.values[culture]}
                />
              </div>
            </div>
          ))}
        </div>
      )}
      {!readOnly && (
        <div className="actions">
          {!editing && (
            <button type="button" className="btn btn-secondary" onClick={open}>
              {t("tradsKeys.edit.action")}
            </button>
          )}
          <button type="button" className="btn btn-secondary" onClick={() => setRenaming(true)}>
            {t("tradsKeys.rename.action")}
          </button>
          <button type="button" className="btn btn-danger" onClick={onRemove}>
            {t("tradsKeys.remove.action")}
          </button>
        </div>
      )}
    </li>
  );
}
