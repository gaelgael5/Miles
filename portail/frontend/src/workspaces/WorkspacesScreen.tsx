import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { useBranchViews } from "../api/branches";
import { ApiError, invalidField } from "../api/http";
import { slugFromLabel } from "../api/secrets";
import { type Workspace, useCreateWorkspace, useWorkspaces } from "../api/workspaces";
import { PageHead } from "../layout/PageHead";
import {
  type WorkspaceSelection,
  type WorkspaceView,
  viewedBranchOf,
} from "../layout/WorkspacesNav";
import { BranchPicker } from "./BranchPicker";
import { BranchViewScreen, hasBranchScreen } from "./branchViews";
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

/** La ligne entière mène au paramétrage (Gael, 24/10/2026) : plus aucun bouton ici, et
 * seules restent l'adresse du dépôt et la branche affichée. Le sélecteur de branche garde
 * son propre geste — `stopPropagation` l'empêche d'ouvrir le paramétrage au passage. */
function WorkspaceRow({
  workspace,
  onOpen,
}: {
  workspace: Workspace;
  onOpen: (view: WorkspaceView) => void;
}) {
  const { t } = useTranslation();
  return (
    <li className="row row-openable">
      <div className="row-main">
        {/* Convention maison des lignes ouvrables : le bouton du titre couvre la ligne,
            et porte le nom accessible. Ce qui doit rester cliquable passe au-dessus. */}
        <button type="button" className="row-open" onClick={() => onOpen("settings")}>
          {workspace.name}
        </button>
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
      {workspace.work_branch !== null && (
        <div
          className="row-control"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
          role="presentation"
        >
          <BranchPicker workspace={workspace} />
        </div>
      )}
    </li>
  );
}

/** Workspaces : une application métier chacun, avec son dépôt et ses cinq droits éprouvés. */
export function WorkspacesScreen({
  selection,
  onSelect,
}: {
  selection: WorkspaceSelection;
  onSelect: (selection: WorkspaceSelection) => void;
}) {
  const { t } = useTranslation();
  const workspaces = useWorkspaces();
  const [creating, setCreating] = useState(false);
  const views = useBranchViews();
  const current = workspaces.data?.find((w) => w.id === selection?.id);
  if (current && selection && hasBranchScreen(current, selection)) {
    return <BranchViewScreen workspace={current} selection={selection} onSelect={onSelect} />;
  }
  if (current) {
    return (
      <WorkspaceSettings
        workspace={current}
        onBack={() => onSelect(null)}
        onOpenBranch={(slug) => onSelect({ id: current.id, view: "branch", branch: slug })}
      />
    );
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
              onSelect({ id, view: "settings" });
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
            <WorkspaceRow
              key={w.id}
              workspace={w}
              onOpen={(view) =>
                onSelect({ id: w.id, view, branch: viewedBranchOf(w, views.data) ?? undefined })
              }
            />
          ))}
        </ul>
      )}
    </section>
  );
}
