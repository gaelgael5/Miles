import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { useChains, useSaveChain } from "../api/chains";
import { proposeSlug } from "../api/contracts";
import { invalidField } from "../api/http";
import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";

function CreateForm({
  target,
  onCreated,
  onCancel,
}: {
  target: WorkTarget;
  onCreated: (slug: string) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [label, setLabel] = useState("");
  const [slug, setSlug] = useState<string | null>(null);
  const shownSlug = slug ?? proposeSlug(label);
  const save = useSaveChain(target, shownSlug);
  const field = invalidField(save.error);

  function submit(event: FormEvent) {
    event.preventDefault();
    // Une chaîne vide est légitime : elle rend le message tel quel, en attendant ses étapes.
    save.mutate({ label, steps: [] }, { onSuccess: (chain) => onCreated(chain.slug) });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("chains.form.title")}>
      <h2>{t("chains.form.title")}</h2>
      <label className="field">
        {t("chains.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label className="field">
        {t("chains.fields.slug")}
        <input required value={shownSlug} onChange={(e) => setSlug(e.target.value)} />
      </label>
      <p className="help">{t("chains.form.slugHelp")}</p>
      {save.isError && (
        <p className="alert" role="alert">
          {t(field ? `chains.errors.field.${field}` : "chains.errors.unexpected")}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={save.isPending}>
          {t("chains.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

/** Chaînes de transformations de la branche (story c1e4424b) : les flux les désignent. */
export function ChainsScreen({
  workspace,
  target,
  onBack,
  onOpen,
}: {
  workspace: Workspace;
  target: WorkTarget;
  onBack: () => void;
  onOpen: (slug: string) => void;
}) {
  const { t } = useTranslation();
  const chains = useChains(target);
  const [creating, setCreating] = useState(false);

  return (
    <section aria-labelledby="chains-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="chains-title">{t("chains.title", { name: workspace.name })}</h1>
          <p className="lead">{t("chains.intro")}</p>
        </div>
        {!creating && !target.readOnly && (
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            {t("chains.add")}
          </button>
        )}
      </div>
      {creating && (
        <CreateForm target={target} onCreated={onOpen} onCancel={() => setCreating(false)} />
      )}
      {chains.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {chains.isSuccess && chains.data.length === 0 && <p className="muted">{t("chains.empty")}</p>}
      {chains.isSuccess && chains.data.length > 0 && (
        <ul className="card-list plain-list">
          {chains.data.map((c) => (
            <li key={c.slug} className="row row-openable">
              <div className="row-main">
                {/* Toute la ligne ouvre la chaîne (fbe9b512) : le bouton du titre la couvre. */}
                <button type="button" className="row-title row-open" onClick={() => onOpen(c.slug)}>
                  {c.label ?? t("chains.unreadable")}
                </button>
                <div className="row-sub mono">transformations/{c.slug}</div>
              </div>
              <div className="cell">
                <div className="caption">{t("chains.captionSteps")}</div>
                <div className="value">
                  {c.steps === null ? "—" : t("chains.steps", { count: c.steps })}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
