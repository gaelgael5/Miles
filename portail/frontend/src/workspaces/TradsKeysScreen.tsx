import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import {
  PAGE_SIZE,
  type TradsKey,
  type ValueChanges,
  useAddTradsKey,
  useDeleteTradsKey,
  useRenameTradsKey,
  useSaveTradsValues,
  useTradsKeys,
} from "../api/tradsKeys";
import { directionOf, useWorkspaceCultures } from "../api/workspaceCultures";
import type { WorkTarget } from "../api/workTarget";
import { TradsKeyRow } from "./TradsKeyRow";
import { tradsKeyError } from "./tradsKeyError";
import { ValueField } from "./ValueField";

function AddForm({
  target,
  context,
  cultures,
  onDone,
}: {
  target: WorkTarget;
  context: string;
  cultures: string[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const add = useAddTradsKey(target, context);
  const all = useWorkspaceCultures(target.workspaceId);
  const [slug, setSlug] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const defaultCulture = all.data?.default ?? "";

  function submit(event: FormEvent) {
    event.preventDefault();
    const changes: ValueChanges = {};
    for (const culture of cultures) {
      const value = values[culture] ?? "";
      // Une culture laissée vide n'est PAS envoyée : son fichier n'a aucune raison d'être
      // réécrit, et c'est le diff git qui y gagne.
      if (value !== "" || culture === defaultCulture) {
        changes[culture] = value;
      }
    }
    add.mutate(
      { slug, values: changes },
      {
        onSuccess: () => {
          setSlug("");
          setValues({});
          onDone();
        },
      },
    );
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("tradsKeys.form.title")}>
      <h2>{t("tradsKeys.form.title")}</h2>
      <label className="field">
        {t("tradsKeys.fields.slug")}
        <input required value={slug} onChange={(e) => setSlug(e.target.value)} />
      </label>
      <p className="help">{t("tradsKeys.form.slugHelp")}</p>
      <div className="trads-values">
        {cultures.map((culture) => (
          <ValueField
            key={culture}
            culture={culture}
            direction={directionOf(all.data, culture)}
            value={values[culture] ?? ""}
            required={culture === defaultCulture}
            onChange={(value) => setValues((current) => ({ ...current, [culture]: value }))}
          />
        ))}
      </div>
      {add.isError && <Refusal error={add.error} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={add.isPending || !slug}>
          {t("tradsKeys.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDone}>
          {t("tradsKeys.form.cancel")}
        </button>
      </div>
    </form>
  );
}

export function Refusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const { key, options } = tradsKeyError(error);
  return (
    <p className="alert" role="alert">
      {t(key, options)}
    </p>
  );
}

/**
 * Saisie des traductions d'un contexte (story 289c8d9f) : une table de clés, un champ par
 * culture du workspace, la culture par défaut en premier.
 *
 * L'INTERFACE NE BASCULE PAS. Seuls les champs et les cellules de valeurs suivent leur
 * culture ; le back-office reste dans la langue de celui qui l'utilise, et la table dans
 * son sens — sans quoi quelqu'un qui traduit du français vers l'arabe verrait son écran
 * entier se retourner à chaque ligne.
 */
export function TradsKeysScreen({
  target,
  context,
  onBack,
}: {
  target: WorkTarget;
  context: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const cultures = useWorkspaceCultures(target.workspaceId);
  const [search, setSearch] = useState("");
  const [untranslated, setUntranslated] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<TradsKey | null>(null);
  const page = useTradsKeys(target, context, {
    search,
    untranslated,
    offset,
    limit: PAGE_SIZE,
  });
  const save = useSaveTradsValues(target, context);
  const rename = useRenameTradsKey(target, context);
  const remove = useDeleteTradsKey(target, context);
  // La culture par défaut en premier, puis les additionnelles : l'ordre est stable d'une
  // ligne à l'autre, sans quoi les colonnes danseraient (critère 3).
  const columns = cultures.data ? [cultures.data.default, ...cultures.data.additional] : [];
  const total = page.data?.total ?? 0;

  function refilter(next: { search?: string; untranslated?: string | null }) {
    // Toute modification du filtre ramène à la première page : rester à l'offset courant
    // afficherait une page vide sur un filtre plus étroit.
    setOffset(0);
    if (next.search !== undefined) {
      setSearch(next.search);
    }
    if (next.untranslated !== undefined) {
      setUntranslated(next.untranslated);
    }
  }

  return (
    <section aria-labelledby="trads-keys-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("tradsKeys.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="trads-keys-title">{t("tradsKeys.title", { context })}</h1>
          <p className="lead">{t("tradsKeys.intro")}</p>
        </div>
        {!target.readOnly && !adding && (
          <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
            {t("tradsKeys.add")}
          </button>
        )}
      </div>
      {adding && (
        <AddForm
          target={target}
          context={context}
          cultures={columns}
          onDone={() => setAdding(false)}
        />
      )}
      <div className="card">
        {/* Les deux filtres sur une MÊME ligne (Gael, 30/10/2026) : ils se combinent, et
            empilés ils repoussaient la liste d'une demi-page sur un écran d'ordinateur. */}
        <div className="trads-filters">
          <label className="field">
            {t("tradsKeys.filter.search")}
            <input
              type="search"
              value={search}
              onChange={(e) => refilter({ search: e.target.value })}
            />
          </label>
          <label className="field">
            {t("tradsKeys.filter.untranslated")}
            <select
              value={untranslated ?? ""}
              onChange={(e) => refilter({ untranslated: e.target.value || null })}
            >
              <option value="">{t("tradsKeys.filter.anyCulture")}</option>
              {columns.map((culture) => (
                <option key={culture} value={culture}>
                  {culture}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="muted" role="status">
          {t("tradsKeys.count", { count: total })}
        </p>
      </div>
      {page.isError && <Refusal error={page.error} />}
      {save.isError && <Refusal error={save.error} />}
      {rename.isError && <Refusal error={rename.error} />}
      {remove.isError && <Refusal error={remove.error} />}
      {page.isPending && (
        <p className="muted" role="status">
          {t("tradsKeys.loading")}
        </p>
      )}
      {page.isSuccess && page.data.keys.length === 0 && (
        <p className="muted" role="status">
          {t(untranslated !== null || search !== "" ? "tradsKeys.noMatch" : "tradsKeys.none")}
        </p>
      )}
      {page.data && page.data.keys.length > 0 && (
        <ul className="card-list plain-list trads-keys">
          {page.data.keys.map((key) => (
            <TradsKeyRow
              key={key.slug}
              entry={key}
              columns={columns}
              cultures={cultures.data}
              readOnly={target.readOnly}
              pending={save.isPending || rename.isPending}
              onSave={(values) => save.mutate({ slug: key.slug, values })}
              onRename={(newSlug) => rename.mutate({ slug: key.slug, newSlug })}
              onRemove={() => setRemoving(key)}
            />
          ))}
        </ul>
      )}
      {total > PAGE_SIZE && (
        <div className="actions">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(offset - PAGE_SIZE, 0))}
          >
            {t("tradsKeys.previous")}
          </button>
          <span className="muted">
            {t("tradsKeys.range", {
              from: offset + 1,
              to: Math.min(offset + PAGE_SIZE, total),
              total,
            })}
          </span>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            {t("tradsKeys.next")}
          </button>
        </div>
      )}
      {removing !== null && (
        <ConfirmDialog
          title={t("tradsKeys.remove.title", { slug: removing.slug })}
          confirmLabel={t("tradsKeys.remove.submit")}
          cancelLabel={t("tradsKeys.form.cancel")}
          onCancel={() => setRemoving(null)}
          onConfirm={() => {
            remove.mutate(removing.slug);
            setRemoving(null);
          }}
        >
          {/* Même régime que le renommage : personne ne sait encore qui référence une clé. */}
          <p className="alert">{t("tradsKeys.remove.warning")}</p>
          <p>
            {t("tradsKeys.remove.values", { count: Object.keys(removing.values).length })}
          </p>
        </ConfirmDialog>
      )}
    </section>
  );
}
