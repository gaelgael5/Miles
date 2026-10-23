import { useTranslation } from "react-i18next";

import { useBranchViews } from "../api/branches";
import { useHoldStatus, useHolds, usePublishHold, useReleaseHold, useTakeHold } from "../api/holds";
import { ApiError } from "../api/http";
import type { Workspace } from "../api/workspaces";
import { baseBranchOf, viewedBranchOf } from "../layout/WorkspacesNav";

type Detail = { code?: string; by?: string; workspace_id?: string; branch?: string };

/** Le refus dit pourquoi, et nomme qui ou quoi bloque (critères 2, 3, 4, 8). */
function HoldRefusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  let message = t("holds.errors.unexpected");
  if (error instanceof ApiError && error.status === 409) {
    const detail = error.detail;
    if (typeof detail === "string") {
      message = t(`holds.errors.${detail}`, { defaultValue: t("holds.errors.unexpected") });
    } else if (typeof detail === "object" && detail !== null) {
      const { code, by, workspace_id, branch } = detail as Detail;
      message = t(`holds.errors.${code ?? "unexpected"}`, { by, workspace: workspace_id, branch });
    }
  }
  return (
    <p className="alert" role="alert">
      {message}
    </p>
  );
}

function MyHold({ workspaceId, slug }: { workspaceId: string; slug: string }) {
  const { t } = useTranslation();
  const status = useHoldStatus(workspaceId, slug, true);
  const publish = usePublishHold(workspaceId, slug);
  const release = useReleaseHold(workspaceId, slug);
  const unpublished = status.data?.unpublished ?? 0;
  const busy = publish.isPending || release.isPending;
  return (
    <>
      <div className="value">
        {t("holds.mine")}
        {status.isSuccess && (
          <span className="muted"> · {t("holds.unpublished", { count: unpublished })}</span>
        )}
      </div>
      <div className="actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy || unpublished === 0}
          onClick={() => publish.mutate()}
        >
          {t("holds.publish")}
        </button>
        <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => release.mutate()}>
          {t("holds.release")}
        </button>
      </div>
      {publish.isSuccess && (
        <p className="notice" role="status">
          {t("holds.published", { count: publish.data.published })}
        </p>
      )}
      {publish.isError && <HoldRefusal error={publish.error} />}
      {release.isError && <HoldRefusal error={release.error} />}
    </>
  );
}

/**
 * Prise de main de la branche regardée, dans « Tous les workspaces » (Gael, 22/10/2026) :
 * on y voit qui l'a, on la prend, on publie, on la rend. Rien sur la racine, qui reste
 * en lecture seule pour tous (dca0eb0e).
 */
export function HoldControl({ workspace }: { workspace: Workspace }) {
  const { t } = useTranslation();
  const views = useBranchViews();
  const slug = viewedBranchOf(workspace, views.data) ?? "";
  const root = slug === baseBranchOf(workspace);
  const holds = useHolds(workspace.id, !root);
  const take = useTakeHold(workspace.id, slug);
  if (root || !holds.isSuccess) {
    return null;
  }
  const hold = holds.data.find((h) => h.slug === slug);
  return (
    <div className="cell">
      <div className="caption">{t("holds.caption")}</div>
      {hold?.mine ? (
        <MyHold workspaceId={workspace.id} slug={slug} />
      ) : hold ? (
        <div className="value">{t("holds.heldBy", { holder: hold.holder })}</div>
      ) : (
        <>
          <div className="actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={take.isPending}
              onClick={() => take.mutate()}
            >
              {t("holds.take")}
            </button>
          </div>
          {take.isError && <HoldRefusal error={take.error} />}
        </>
      )}
    </div>
  );
}
