import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, ConfirmDialog } from "@miles/socle-web";
import { useBranchViews } from "../api/branches";
import {
  type Shelf,
  useHoldStatus,
  useHolds,
  usePublishHold,
  useReleaseHold,
  useShelves,
  useTakeHold,
  useUnlockHold,
} from "../api/holds";
import type { Workspace } from "../api/workspaces";
import { baseBranchOf, viewedBranchOf } from "../layout/WorkspacesNav";

type Detail = {
  code?: string;
  by?: string;
  workspace_id?: string;
  branch?: string;
  files?: string[];
};

/** Le refus dit pourquoi, et nomme qui ou quoi bloque (critères 2, 3, 4, 8). */
function HoldRefusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  let message = t("holds.errors.unexpected");
  if (error instanceof ApiError && error.status === 409) {
    const detail = error.detail;
    if (typeof detail === "string") {
      message = t(`holds.errors.${detail}`, { defaultValue: t("holds.errors.unexpected") });
    } else if (typeof detail === "object" && detail !== null) {
      const { code, by, workspace_id, branch, files } = detail as Detail;
      message = t(`holds.errors.${code ?? "unexpected"}`, {
        by,
        workspace: workspace_id,
        branch,
        files: files?.join(", "),
      });
    }
  }
  return (
    <p className="alert" role="alert">
      {message}
    </p>
  );
}

/**
 * Déverrouiller qui tient la branche (story fd1eb7da) : son travail non publié est rangé
 * sur la forge avec son propre jeton, puis la branche se libère. Après confirmation.
 */
function Unlock({
  workspaceId,
  slug,
  holder,
  onDone,
}: {
  workspaceId: string;
  slug: string;
  holder: string;
  onDone: (result: { shelf: Shelf | null }) => void;
}) {
  const { t } = useTranslation();
  const unlock = useUnlockHold(workspaceId, slug);
  const [confirming, setConfirming] = useState(false);
  return (
    <>
      <div className="actions">
        <button
          type="button"
          className="btn btn-danger"
          disabled={unlock.isPending}
          onClick={() => setConfirming(true)}
        >
          {t("holds.unlock")}
        </button>
      </div>
      {unlock.isError && <HoldRefusal error={unlock.error} />}
      {confirming && (
        <ConfirmDialog
          title={t("holds.unlockConfirm.title", { holder })}
          confirmLabel={t("holds.unlock")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            unlock.mutate(undefined, { onSuccess: onDone });
          }}
        >
          {t("holds.unlockConfirm.body")}
        </ConfirmDialog>
      )}
    </>
  );
}

/** Après un déverrouillage, ce qu'il est advenu du travail : rangé, ou rien à ranger. */
function Unlocked({ shelf }: { shelf: Shelf | null }) {
  const { t } = useTranslation();
  return (
    <p className="notice" role="status">
      {shelf ? t("holds.unlocked.shelved", { branch: shelf.shelf_branch }) : t("holds.unlocked.free")}
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
  const shelves = useShelves(workspace.id, !root);
  const take = useTakeHold(workspace.id, slug);
  const [unlocked, setUnlocked] = useState<{ shelf: Shelf | null } | null>(null);
  if (root || !holds.isSuccess) {
    return null;
  }
  const hold = holds.data.find((h) => h.slug === slug);
  const shelved = shelves.data?.some((s) => s.slug === slug && s.mine) ?? false;
  return (
    <div className="cell">
      <div className="caption">{t("holds.caption")}</div>
      {hold?.mine ? (
        <MyHold workspaceId={workspace.id} slug={slug} />
      ) : hold ? (
        <>
          <div className="value">{t("holds.heldBy", { holder: hold.holder })}</div>
          <Unlock
            workspaceId={workspace.id}
            slug={slug}
            holder={hold.holder}
            onDone={setUnlocked}
          />
        </>
      ) : (
        <>
          {unlocked && <Unlocked shelf={unlocked.shelf} />}
          {shelved && (
            <p className="notice" role="note">
              {t("holds.shelvedMine")}
            </p>
          )}
          <div className="actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={take.isPending}
              onClick={() => take.mutate()}
            >
              {t(shelved ? "holds.resume" : "holds.take")}
            </button>
          </div>
          {take.isError && <HoldRefusal error={take.error} />}
        </>
      )}
    </div>
  );
}
