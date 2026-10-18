import { useTranslation } from "react-i18next";

import { HealthStatus } from "./health/HealthStatus";

export function App() {
  const { t } = useTranslation();
  return (
    <main>
      <h1>{t("app.title")}</h1>
      <HealthStatus />
    </main>
  );
}
