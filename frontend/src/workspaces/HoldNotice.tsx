import { useTranslation } from "react-i18next";

import { useHolds } from "../api/holds";

/** Sur une branche enfant dont on n'a pas la main : qui l'a, et où la prendre. */
export function HoldNotice({ workspaceId, branch }: { workspaceId: string; branch: string }) {
  const { t } = useTranslation();
  const holds = useHolds(workspaceId);
  if (!holds.isSuccess) {
    return null;
  }
  const hold = holds.data.find((h) => h.slug === branch);
  return (
    <p className="notice" role="note">
      {hold ? t("holds.notice.heldBy", { holder: hold.holder }) : t("holds.notice.free")}
    </p>
  );
}
