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
  baseBranchOf,
  viewedBranchOf,
  viewsOf,
} from "../layout/WorkspacesNav";
import { BranchForm } from "./BranchForm";
import { BranchPicker } from "./BranchPicker";
import { BranchScreen } from "./BranchScreen";
import { ContractScreen } from "./ContractScreen";
import { ContractsScreen } from "./ContractsScreen";
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

function WorkspaceRow({
  workspace,
  onOpen,
  onBranch,
}: {
  workspace: Workspace;
  onOpen: (view: WorkspaceView) => void;
  onBranch: () => void;
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
      {workspace.work_branch === null ? (
        <div className="cell">
          <div className="caption">{t("workspaces.card.captionWorkBranch")}</div>
          <div className="value mono">—</div>
        </div>
      ) : (
        <BranchPicker workspace={workspace} />
      )}
      <div className="actions row-actions">
        {workspace.work_branch !== null && (
          <button type="button" className="btn btn-secondary" onClick={onBranch}>
            {t("branches.add")}
          </button>
        )}
        {viewsOf(workspace).map((view) => (
          <button key={view} type="button" className="btn btn-secondary" onClick={() => onOpen(view)}>
            {t(`workspaces.card.${view}`)}
          </button>
        ))}
      </div>
    </li>
  );
}

/** Écran d'une vue de branche ; null pour le paramétrage du workspace. */
function branchScreen(
  workspace: Workspace,
  selection: NonNullable<WorkspaceSelection>,
  onSelect: (selection: WorkspaceSelection) => void,
) {
  const branch = selection.branch ?? baseBranchOf(workspace);
  if (selection.view === "settings" || branch === null) {
    return null;
  }
  const target = { workspaceId: workspace.id, branch };
  const back = () => onSelect(null);
  // La clé suit la branche : changer de branche repart d'un écran neuf, sans état d'une
  // autre branche (formulaire ouvert, aperçu) recopié par erreur.
  const key = `${branch}/${selection.view}/${selection.contract ?? ""}`;
  if (selection.view === "contracts" && selection.contract !== undefined) {
    return (
      <ContractScreen
        key={key}
        target={target}
        slug={selection.contract}
        onBack={() => onSelect({ id: workspace.id, view: "contracts", branch })}
      />
    );
  }
  if (selection.view === "contracts") {
    return (
      <ContractsScreen
        key={key}
        workspace={workspace}
        target={target}
        onBack={back}
        onOpen={(contract) => onSelect({ id: workspace.id, view: "contracts", branch, contract })}
      />
    );
  }
  if (selection.view === "dataModels") {
    return <DataModelsScreen key={key} workspace={workspace} target={target} onBack={back} />;
  }
  return <BranchScreen key={key} workspace={workspace} target={target} onBack={back} />;
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
  const [branching, setBranching] = useState<Workspace | null>(null);
  const views = useBranchViews();
  const current = workspaces.data?.find((w) => w.id === selection?.id);
  const screen = current && selection ? branchScreen(current, selection, onSelect) : null;

  if (screen) {
    return screen;
  }
  if (current) {
    return <WorkspaceSettings workspace={current} onBack={() => onSelect(null)} />;
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
      {branching && (
        <BranchForm
          workspace={branching}
          onDone={(slug) => {
            setBranching(null);
            if (slug) {
              onSelect({ id: branching.id, view: "branch", branch: slug });
            }
          }}
        />
      )}
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
              onBranch={() => setBranching(w)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
