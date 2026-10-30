import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import {
  type TradsContext,
  contextNameFrom,
  useAddTradsContext,
  useDeleteTradsContext,
  useRelabelTradsContext,
  useRemovalPreview,
  useTradsContexts,
} from "../api/trads";
import type { WorkTarget } from "../api/workTarget";
import { Obsoletes } from "./TradsObsoletes";
import { Refusal } from "./tradsRefusal";

/** Le contexte est VIDE, pas couvert à cent pour cent : zéro sur zéro n'est pas une
 * bonne nouvelle (critère 8), et l'écran ne doit pas le présenter comme terminé. */
function Coverage({ context }: { context: TradsContext }) {
  const { t } = useTranslation();
  if (context.keys === 0) {
    return <span className="badge">{t("trads.empty")}</span>;
  }
  return (
    <>
      {Object.entries(context.translated).map(([culture, done]) => (
        <span
          key={culture}
          className={done === context.keys ? "badge badge-success" : "badge"}
          title={t("trads.coverageTitle", { culture })}
        >
          {culture} {done}/{context.keys}
        </span>
      ))}
    </>
  );
}

function CreateForm({ target, onDone }: { target: WorkTarget; onDone: () => void }) {
  const { t } = useTranslation();
  const add = useAddTradsContext(target);
  const [label, setLabel] = useState("");
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const shownName = nameTouched ? name : contextNameFrom(label);

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate({ name: shownName, label }, { onSuccess: onDone });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("trads.form.title")}>
      <h2>{t("trads.form.title")}</h2>
      <label className="field">
        {t("trads.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label className="field">
        {t("trads.fields.name")}
        <input
          required
          value={shownName}
          onChange={(e) => {
            setNameTouched(true);
            setName(e.target.value);
          }}
        />
      </label>
      {/* Dire que le nom est FIGÉ avant la création, pas après : il entre dans le chemin
          sur disque et dans tout ce qui référencera ses clés. */}
      <p className="help">{t("trads.form.nameHelp")}</p>
      {add.isError && <Refusal error={add.error} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={add.isPending || !shownName}>
          {t("trads.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDone}>
          {t("trads.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function RelabelForm({
  target,
  context,
  onDone,
}: {
  target: WorkTarget;
  context: TradsContext;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const relabel = useRelabelTradsContext(target);
  const [label, setLabel] = useState(context.label);

  function submit(event: FormEvent) {
    event.preventDefault();
    relabel.mutate({ name: context.name, label }, { onSuccess: onDone });
  }

  return (
    <form onSubmit={submit} aria-label={t("trads.relabel.title", { name: context.name })}>
      <label className="field">
        {t("trads.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      {relabel.isError && <Refusal error={relabel.error} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={relabel.isPending}>
          {t("trads.relabel.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDone}>
          {t("trads.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function RemoveDialog({
  target,
  context,
  onDone,
}: {
  target: WorkTarget;
  context: TradsContext;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const preview = useRemovalPreview(target, context.name);
  const remove = useDeleteTradsContext(target);
  const populated = (preview.data?.keys ?? 0) > 0;

  return (
    <ConfirmDialog
      title={t("trads.remove.title", { label: context.label })}
      confirmLabel={t("trads.remove.submit")}
      cancelLabel={t("trads.form.cancel")}
      onCancel={onDone}
      onConfirm={() => remove.mutate(context.name, { onSuccess: onDone })}
    >
      {/* Le geste dangereux de cet écran : la confirmation annonce ce qui disparaît, et
          combien de valeurs toutes cultures confondues (critère 6). */}
      {preview.isPending && <p className="muted">{t("trads.remove.counting")}</p>}
      {populated ? (
        <p className="alert">
          {t("trads.remove.populated", {
            keys: preview.data?.keys ?? 0,
            values: preview.data?.values ?? 0,
          })}
        </p>
      ) : (
        preview.isSuccess && <p>{t("trads.remove.empty", { label: context.label })}</p>
      )}
      <p className="muted">{t("trads.remove.revertible")}</p>
      {remove.isError && <Refusal error={remove.error} />}
    </ConfirmDialog>
  );
}

/**
 * Contextes de traduction de la branche (story 623898d1) : un contexte regroupe les clés
 * d'un même usage, et il EST le répertoire sous lequel elles vivent.
 *
 * Les cultures de la couverture sont celles du workspace, réglées dans son paramétrage —
 * pas les cultures actives de l'application, qui sont les langues du back-office.
 */
export function TradsScreen({
  target,
  onBack,
  onOpen,
}: {
  target: WorkTarget;
  onBack: () => void;
  // Ouvre la saisie des clés du contexte. Absent : la liste ne navigue pas.
  onOpen?: (context: string) => void;
}) {
  const { t } = useTranslation();
  const contexts = useTradsContexts(target);
  const [creating, setCreating] = useState(false);
  const [relabelling, setRelabelling] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const found = (name: string | null) => contexts.data?.find((c) => c.name === name) ?? null;
  const toRemove = found(removing);

  return (
    <section aria-labelledby="trads-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="trads-title">{t("trads.title")}</h1>
          <p className="lead">{t("trads.intro")}</p>
        </div>
        {!target.readOnly && !creating && (
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            {t("trads.add")}
          </button>
        )}
      </div>
      {creating && <CreateForm target={target} onDone={() => setCreating(false)} />}
      {contexts.isError && <Refusal error={contexts.error} />}
      {contexts.isPending && (
        <p className="muted" role="status">
          {t("trads.loading")}
        </p>
      )}
      {contexts.isSuccess && contexts.data.length === 0 && !creating && (
        <p className="muted" role="status">
          {t("trads.none")}
        </p>
      )}
      {contexts.data && contexts.data.length > 0 && (
        <ul className="card-list plain-list">
          {contexts.data.map((context) => (
            <li className="row row-openable" key={context.name}>
              <div className="row-main">
                {/* Convention maison des lignes ouvrables : le bouton du titre couvre la
                    ligne et porte le nom accessible (story fbe9b512). */}
                {onOpen ? (
                  <button
                    type="button"
                    className="row-open"
                    onClick={() => onOpen(context.name)}
                  >
                    {context.label}
                  </button>
                ) : (
                  context.label
                )}
                <div className="row-sub mono">{context.name}</div>
                {relabelling === context.name && (
                  <RelabelForm
                    target={target}
                    context={context}
                    onDone={() => setRelabelling(null)}
                  />
                )}
              </div>
              <div className="cell">
                <div className="caption">{t("trads.keys")}</div>
                <div className="value">{context.keys}</div>
              </div>
              <div className="cell">
                <Coverage context={context} />
              </div>
              <Obsoletes target={target} context={context} readOnly={target.readOnly} />
              {!target.readOnly && (
                <div className="actions">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setRelabelling(context.name)}
                  >
                    {t("trads.relabel.action")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-danger"
                    onClick={() => setRemoving(context.name)}
                  >
                    {t("trads.remove.action")}
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {toRemove !== null && (
        <RemoveDialog target={target} context={toRemove} onDone={() => setRemoving(null)} />
      )}
    </section>
  );
}
