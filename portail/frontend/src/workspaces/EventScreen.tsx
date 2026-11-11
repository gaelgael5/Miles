import type { JsonSchema } from "jsonjoy-builder";
import { Suspense, lazy, useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import { SHARED_SCOPE, useDataModels } from "../api/dataModels";
import type { WorkTarget } from "../api/workTarget";
import {
  type WorkflowEventContent,
  useEventSocle,
  useReplaceWorkflowEvent,
  useWorkflowEvent,
} from "../api/workflowEvents";
import { ImportSmart } from "../dataModels/ImportSmart";
import { isBlankSchema, parseSchema, sameSchema, schemaText } from "../dataModels/schemaText";
import { useSaveShortcut } from "../layout/useSaveShortcut";
import { socleClash, withoutSocle } from "./EventSocle";
import { ModelRefusal } from "./ModelRefusal";

// Le MÊME éditeur que les modèles de données, chargé paresseusement par le même module :
// un événement est un JSON Schema écrit en YAML, et c'est tout l'intérêt de la décision
// du 11/11/2026 — la liste est séparée, l'outil de construction ne l'est pas.
const SchemaEditor = lazy(() => import("../dataModels/SchemaEditor"));
// Le socle, dans le MÊME éditeur visuel que les champs métier, verrouillé — c'est ce
// qui fait voir qu'un événement en dérive (Gael, 11/11/2026, d'après la vue
// « Événements » du playground d'urban-workflow). Chargé paresseusement comme l'autre :
// c'est le même composant lourd, et le reste du portail ne paie pas son poids.
const LockedSchema = lazy(() => import("../dataModels/LockedSchema"));

/** Le schéma déduit, sous l'identité que l'événement tient déjà de sa déclaration. */
function withIdentity(current: JsonSchema, inferred: Record<string, unknown>): JsonSchema {
  const head: Record<string, unknown> = {};
  if (typeof current === "object" && current !== null) {
    const from = current as Record<string, unknown>;
    for (const key of ["$schema", "$id", "title"]) {
      if (typeof from[key] === "string") {
        head[key] = from[key];
      }
    }
  }
  return { ...head, ...inferred } as JsonSchema;
}

/** Éditeur visuel à gauche, YAML à droite : rien ne part au serveur avant « Enregistrer ». */
function Editor({
  target,
  event,
  saved,
  onDirty,
  onSaved,
}: {
  target: WorkTarget;
  event: WorkflowEventContent;
  saved: boolean;
  onDirty: (dirty: boolean) => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const replace = useReplaceWorkflowEvent(target, event);
  const models = useDataModels(target);
  const socle = useEventSocle(target);
  const [text, setText] = useState(event.content);
  const [parsed, setParsed] = useState(() => parseSchema(event.content));
  const [importing, setImporting] = useState(false);
  const [dropped, setDropped] = useState<string[]>([]);
  const dirty = !sameSchema(text, event.content);
  const blank = isBlankSchema(parsed);
  // Signalée AVANT d'enregistrer : le serveur refuse `propriete_du_socle`, mais un refus
  // au moment d'enregistrer arrive après le travail.
  const clash = parsed.ok ? socleClash(parsed.schema, socle.data) : [];

  function changed(next: string) {
    onDirty(!sameSchema(next, event.content));
  }

  function fromVisual(schema: JsonSchema) {
    const next = schemaText(schema);
    setText(next);
    setParsed({ ok: true, schema });
    changed(next);
  }

  function fromYaml(next: string) {
    setText(next);
    setParsed(parseSchema(next));
    changed(next);
  }

  function save() {
    replace.mutate(text, {
      onSuccess: () => {
        onDirty(false);
        onSaved();
      },
    });
  }

  const canSave = !target.readOnly && dirty && !replace.isPending;
  useSaveShortcut(canSave ? save : null);

  return (
    <>
      <div className="page-head">
        <div>
          <h1 id="workflow-event-title">{event.label ?? event.name}</h1>
          <p className="lead">
            <span className="mono">{event.name}</span> ·{" "}
            {event.scope === SHARED_SCOPE ? t("dataModels.list.shared") : event.scope} ·{" "}
            <span title={t("dataModels.schema.versionHelp")}>
              {t("dataModels.schema.version", { version: event.version ?? "—" })}
            </span>
          </p>
        </div>
        {!target.readOnly && (
          <div className="actions">
            {dirty && <span className="badge badge-warning">{t("dataModels.editor.unsaved")}</span>}
            {blank && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setImporting(true)}
              >
                {t("dataModels.import.action")}
              </button>
            )}
            <button
              type="button"
              className="btn btn-primary"
              disabled={!canSave}
              title={t("dataModels.editor.saveShortcut")}
              onClick={save}
            >
              {t("dataModels.editor.save")}
            </button>
          </div>
        )}
      </div>
      {importing && (
        <ImportSmart
          target={target}
          path={event.path}
          onCancel={() => setImporting(false)}
          onImported={(inferred) => {
            setImporting(false);
            const [metier, retirees] = withoutSocle(inferred, socle.data);
            setDropped(retirees);
            fromVisual(withIdentity(parsed.ok ? parsed.schema : {}, metier));
          }}
        />
      )}
      {dropped.length > 0 && (
        <p className="notice" role="status">
          {t("workflowEvents.import.socleDropped", { list: dropped.join(", ") })}
        </p>
      )}
      {saved && !dirty && (
        <p className="notice" role="status">
          {t("dataModels.editor.saved")}
        </p>
      )}
      {replace.isError && <ModelRefusal error={replace.error} />}
      {/* LE SOCLE D'ABORD, et c'est tout l'objet du 11/11/2026 : un événement n'est pas
          un schéma qui aurait un appendice, c'est un schéma qui DÉRIVE d'un type de base.
          Montré après les champs métier, ou dans un tableau à part, il se lisait comme une
          annexe — et personne ne voyait la dérivation. */}
      {socle.isSuccess && (
        <div className="card" role="group" aria-label={t("workflowEvents.socle.title")}>
          <h2>{t("workflowEvents.socle.title")}</h2>
          <p className="help">{t("workflowEvents.socle.help")}</p>
          <Suspense
            fallback={
              <p className="muted" role="status">
                {t("dataModels.loading")}
              </p>
            }
          >
            <LockedSchema schema={socle.data as never} />
          </Suspense>
        </div>
      )}
      <div className="card" role="group" aria-label={t("workflowEvents.business.title")}>
        <h2>{t("workflowEvents.business.title")}</h2>
        {clash.length > 0 && (
          <div className="alert" role="alert">
            {t("workflowEvents.socle.clash", { list: clash.join(", ") })}
          </div>
        )}
        <Suspense
          fallback={
            <p className="muted" role="status">
              {t("dataModels.loading")}
            </p>
          }
        >
          <SchemaEditor
            target={target}
            model={event}
            models={models.data ?? []}
            text={text}
            parsed={parsed}
            onVisual={fromVisual}
            onYaml={fromYaml}
          />
        </Suspense>
        <p className="help">{t("workflowEvents.editor.help")}</p>
      </div>
    </>
  );
}

/**
 * Édition d'un événement : son schéma métier s'écrit ici, avec le même outil qu'un modèle.
 * Sans la main, ou sur la racine, il se lit sans se modifier.
 */
export function EventScreen({
  target,
  scope,
  name,
  onBack,
}: {
  target: WorkTarget;
  scope: string;
  name: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const event = useWorkflowEvent(target, { scope, name });
  const data = event.data;
  const [dirty, setDirty] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [saved, setSaved] = useState(false);

  return (
    <section aria-labelledby="workflow-event-title">
      <button
        type="button"
        className="btn btn-secondary back"
        onClick={() => (dirty ? setLeaving(true) : onBack())}
      >
        {t("workflowEvents.editor.back")}
      </button>
      {leaving && (
        <ConfirmDialog
          title={t("dataModels.editor.leaveTitle")}
          confirmLabel={t("dataModels.editor.leave")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setLeaving(false)}
          onConfirm={onBack}
        >
          <p>{t("dataModels.editor.leaveBody")}</p>
        </ConfirmDialog>
      )}
      {event.isPending && (
        <p className="muted" role="status">
          {t("dataModels.loading")}
        </p>
      )}
      {event.isError && <ModelRefusal error={event.error} />}
      {data && (
        <Editor
          key={data.content}
          target={target}
          event={data}
          saved={saved}
          onDirty={(value) => {
            setDirty(value);
            if (value) setSaved(false);
          }}
          onSaved={() => setSaved(true)}
        />
      )}
    </section>
  );
}
