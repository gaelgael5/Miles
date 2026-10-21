import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, invalidField } from "../api/http";
import { slugFromLabel } from "../api/secrets";
import { type Workspace, useCreateWorkspace, useWorkspaces } from "../api/workspaces";
import { PageHead } from "../layout/PageHead";
import { DataModelsScreen } from "./DataModelsScreen";
import { WorkspaceSettings } from "./WorkspaceSettings";

function errorKey(error: unknown): string {
  const field = invalidField(error);
  if (field !== null) {
    return `workspaces.errors.invalid.${field}`;
  }
  if (error instanceof ApiError && error.status === 409) {
    return `workspaces.errors.conflict.${String(error.detail)}`;
  }
  return "workspaces.errors.unexpected";
}

/**
 * Création par le nom seul (Gael, 21/10/2026) : dépôt, accès et service de sécurité se
 * règlent ensuite dans le paramétrage. L'identifiant suit le nom tant qu'on ne l'a pas
 * saisi soi-même.
 */
function CreateForm({ onDone }: { onDone: (id: string) => void }) {
  const { t } = useTranslation();
  const create = useCreateWorkspace();
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [idTouched, setIdTouched] = useState(false);
  const shownId = idTouched ? id : slugFromLabel(name);

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate({ id: shownId, name }, { onSuccess: (w) => onDone(w.id) });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("workspaces.form.title")}>
      <h2>{t("workspaces.form.title")}</h2>
      <label className="field">
        {t("workspaces.fields.name")}
        <input required value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label className="field">
        {t("workspaces.fields.id")}
        <input
          required
          value={shownId}
          onChange={(e) => {
            setIdTouched(true);
            setId(e.target.value);
          }}
        />
      </label>
      <p className="help">{t("workspaces.form.idHelp")}</p>
      {create.isError && <p className="alert" role="alert">{t(errorKey(create.error))}</p>}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={create.isPending}>
          {t("workspaces.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => onDone("")}>
          {t("workspaces.form.cancel")}
        </button>
      </div>
    </form>
  );
}

type View = "settings" | "dataModels";

function WorkspaceRow({
  workspace,
  onOpen,
}: {
  workspace: Workspace;
  onOpen: (view: View) => void;
}) {
  const { t } = useTranslation();
  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{workspace.name}</div>
        <div className="row-sub">{workspace.id}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("workspaces.card.captionRepository")}</div>
        <div className="value">
          {workspace.repo_url ? (
            <span className="mono">{workspace.repo_url}</span>
          ) : (
            <span className="badge badge-warning">{t("workspaces.card.noRepository")}</span>
          )}
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("workspaces.card.captionSecurity")}</div>
        <div className="value">{workspace.security_service_id ?? "—"}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("workspaces.card.captionWorkBranch")}</div>
        <div className="value mono">{workspace.work_branch ?? "—"}</div>
      </div>
      <div className="actions row-actions">
        {/* Les modèles s'écrivent dans la branche de travail : sans elle, rien à ouvrir. */}
        {workspace.work_branch !== null && (
          <button type="button" className="btn btn-secondary" onClick={() => onOpen("dataModels")}>
            {t("workspaces.card.dataModels")}
          </button>
        )}
        <button type="button" className="btn btn-secondary" onClick={() => onOpen("settings")}>
          {t("workspaces.card.settings")}
        </button>
      </div>
    </li>
  );
}

/** Workspaces : une application métier chacun, avec son dépôt et ses cinq droits éprouvés. */
export function WorkspacesScreen() {
  const { t } = useTranslation();
  const workspaces = useWorkspaces();
  const [creating, setCreating] = useState(false);
  // Sous-écran ouvert : le workspace et la vue choisie, sinon la liste.
  const [selected, setSelected] = useState<{ id: string; view: View } | null>(null);
  const current = workspaces.data?.find((w) => w.id === selected?.id);

  if (current && selected?.view === "dataModels") {
    return <DataModelsScreen workspace={current} onBack={() => setSelected(null)} />;
  }
  if (current) {
    return <WorkspaceSettings workspace={current} onBack={() => setSelected(null)} />;
  }
  return (
    <section aria-labelledby="workspaces-title">
      <PageHead
        id="workspaces-title"
        title={t("workspaces.title")}
        lead={t("workspaces.intro")}
        action={
          !creating && (
            <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
              {t("workspaces.add")}
            </button>
          )
        }
      />
      {creating && (
        <CreateForm
          onDone={(id) => {
            setCreating(false);
            // Juste créé, il n'a pas de dépôt : on enchaîne sur son paramétrage.
            if (id) {
              setSelected({ id, view: "settings" });
            }
          }}
        />
      )}
      {workspaces.isError && <p className="alert" role="alert">{t("workspaces.errors.unreachable")}</p>}
      {workspaces.isSuccess && workspaces.data.length === 0 && (
        <p className="muted">{t("workspaces.empty")}</p>
      )}
      {(workspaces.data?.length ?? 0) > 0 && (
        <ul className="card-list plain-list">
          {workspaces.data?.map((w) => (
            <WorkspaceRow key={w.id} workspace={w} onOpen={(view) => setSelected({ id: w.id, view })} />
          ))}
        </ul>
      )}
    </section>
  );
}
