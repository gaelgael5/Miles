import { useTranslation } from "react-i18next";

/** Sur la racine, rien ne se modifie : on dit où aller plutôt que de griser sans raison. */
export function RootReadOnlyNotice() {
  const { t } = useTranslation();
  return (
    <p className="notice" role="note">
      {t("branches.rootReadOnly")}
    </p>
  );
}
