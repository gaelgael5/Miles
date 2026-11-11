import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import { proposeSlug } from "../api/contracts";
import { SHARED_SCOPE } from "../api/dataModels";
import { useDomains } from "../api/domains";
import type { WorkTarget } from "../api/workTarget";
import {
  type WorkflowEvent,
  useDeclareWorkflowEvent,
  useDeleteWorkflowEvent,
  useWorkflowEvents,
} from "../api/workflowEvents";
import type { Workspace } from "../api/workspaces";
import { DomainForm } from "./DomainForm";
import { ModelRefusal } from "./ModelRefusal";

// Le nom d'un événement est plus étroit que celui d'un modèle : le DSL du moteur refuse
// le tiret (mesuré le 11/11/2026). La proposition faite d'après le libellé doit donc le
// remplacer, sinon « Demande soumise » proposerait « demande-soumise », aussitôt refusé
// par le serveur — un aller-retour pour une règle que l'écran connaît déjà.
function proposeEventName(label: string): string {
  return proposeSlug(label).replaceAll("-", "_");
}

const REFUSED_FIELDS = { name: "workflowEvents.errors.invalid.name" };

/** Déclaration en deux temps, comme pour un modèle : l'identité ici, le schéma ensuite. */
function CreateForm({
  target,
  onCreated,
  onCancel,
}: {
  target: WorkTarget;
  onCreated: (event: WorkflowEvent) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const declare = useDeclareWorkflowEvent(target);
  const [label, setLabel] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [scope, setScope] = useState(SHARED_SCOPE);
  const domains = useDomains(target);
  const shownSlug = slugTouched ? slug : proposeEventName(label);

  function submit(event: FormEvent) {
    event.preventDefault();
    declare.mutate({ scope, label, slug: shownSlug }, { onSuccess: onCreated });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("workflowEvents.form.title")}>
      <h2>{t("workflowEvents.form.title")}</h2>
      <label className="field">
        {t("workflowEvents.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label className="field">
        {t("workflowEvents.fields.slug")}
        <input
          required
          className="mono"
          value={shownSlug}
          onChange={(e) => {
            setSlugTouched(true);
            setSlug(e.target.value);
          }}
        />
      </label>
      <p className="help">{t("workflowEvents.form.slugHelp")}</p>
      <label className="field">
        {t("workflowEvents.fields.domain")}
        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value={SHARED_SCOPE}>{t("dataModels.list.shared")}</option>
          {(domains.data ?? []).map((d) => (
            <option key={d.name} value={d.name}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <p className="help">{t("workflowEvents.form.domainHelp")}</p>
      {declare.isError && <ModelRefusal error={declare.error} fields={REFUSED_FIELDS} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={declare.isPending}>
          {t("workflowEvents.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function EventRow({
  target,
  event,
  onOpen,
}: {
  target: WorkTarget;
  event: WorkflowEvent;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteWorkflowEvent(target);

  return (
    <li className="row row-openable">
      <div className="row-main">
        <button type="button" className="row-title row-open" onClick={onOpen}>
          {event.label ?? event.name}
        </button>
        {/* Le nom du DSL, pas le libellé : c'est lui qu'on écrit dans un `DEFINE EVENT`,
            et c'est la seule chose qu'un script de workflow connaisse de cet écran. */}
        <div className="row-sub mono">{event.name}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("dataModels.list.captionScope")}</div>
        <div className="value">
          {event.scope === SHARED_SCOPE ? t("dataModels.list.shared") : event.scope}
        </div>
      </div>
      <div className="actions row-actions">
        {!target.readOnly && (
          <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
            {t("dataModels.list.delete")}
          </button>
        )}
      </div>
      {remove.isError && (
        <div className="row-detail">
          <ModelRefusal error={remove.error} />
        </div>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("workflowEvents.deleteConfirm.title")}
          confirmLabel={t("dataModels.deleteConfirm.confirm")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate(event);
          }}
        >
          <p>{t("workflowEvents.deleteConfirm.body", { path: event.path })}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

/**
 * Référentiel d'événements du workspace (Gael, 11/11/2026) : sa propre liste, à côté des
 * modèles de données et jamais mêlée à eux. Ce que cet écran produit, c'est ce qu'un
 * `DEFINE EVENT … AS @nom` d'un script de workflow désignera.
 */
export function EventsScreen({
  workspace,
  target,
  onBack,
  onOpen,
}: {
  workspace: Workspace;
  target: WorkTarget;
  onBack: () => void;
  onOpen: (event: WorkflowEvent) => void;
}) {
  const { t } = useTranslation();
  const events = useWorkflowEvents(target);
  const [creating, setCreating] = useState(false);
  const [addingDomain, setAddingDomain] = useState(false);
  const [added, setAdded] = useState<string | null>(null);

  return (
    <section aria-labelledby="workflow-events-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="workflow-events-title">{t("workflowEvents.title", { name: workspace.name })}</h1>
          <p className="lead">
            {t("workflowEvents.intro")} <span className="mono">{workspace.work_branch}</span>
          </p>
        </div>
        {!target.readOnly && (
          <div className="actions">
            {!addingDomain && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setAdded(null);
                  setAddingDomain(true);
                }}
              >
                {t("dataModels.addDomain")}
              </button>
            )}
            {!creating && (
              <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
                {t("workflowEvents.add")}
              </button>
            )}
          </div>
        )}
      </div>
      {addingDomain && (
        <DomainForm
          target={target}
          onAdded={(domain) => {
            setAddingDomain(false);
            setAdded(domain.name);
          }}
          onCancel={() => setAddingDomain(false)}
        />
      )}
      {added !== null && (
        <p className="notice" role="status">
          {t("dataModels.domainForm.added", { name: added })}
        </p>
      )}
      {creating && (
        <CreateForm target={target} onCreated={onOpen} onCancel={() => setCreating(false)} />
      )}
      {events.isPending && (
        <p className="muted" role="status">
          {t("dataModels.loading")}
        </p>
      )}
      {events.isError && <ModelRefusal error={events.error} />}
      {events.isSuccess && events.data.length === 0 && (
        <p className="muted">{t("workflowEvents.empty")}</p>
      )}
      {events.isSuccess && events.data.length > 0 && (
        <ul className="card-list plain-list">
          {events.data.map((e) => (
            <EventRow key={e.path} target={target} event={e} onOpen={() => onOpen(e)} />
          ))}
        </ul>
      )}
    </section>
  );
}
