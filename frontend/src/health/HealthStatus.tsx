import { useTranslation } from "react-i18next";

import { useHealth } from "../api/health";

export function HealthStatus() {
  const { t } = useTranslation();
  const { data, isPending, isError } = useHealth();

  if (isPending) {
    return <p role="status">{t("health.loading")}</p>;
  }
  if (isError) {
    return <p role="alert">{t("health.unreachable")}</p>;
  }
  const schema =
    data.schema_version === null
      ? t("health.schemaNone", { expected: data.expected_schema_version })
      : t("health.schema", {
          current: data.schema_version,
          expected: data.expected_schema_version,
        });
  return (
    <section aria-labelledby="health-title">
      <h2 id="health-title">{t("health.title")}</h2>
      <p role={data.status === "ok" ? "status" : "alert"}>
        {t(data.status === "ok" ? "health.ok" : "health.degraded")}
      </p>
      <ul>
        <li>{t(data.database === "up" ? "health.databaseUp" : "health.databaseDown")}</li>
        <li>{schema}</li>
      </ul>
    </section>
  );
}
