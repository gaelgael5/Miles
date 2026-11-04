import { useTranslation } from "react-i18next";

import { useHealth } from "../api/health";
import { PageHead } from "../layout/PageHead";

export function HealthStatus() {
  const { t } = useTranslation();
  const { data, isPending, isError } = useHealth();

  if (isPending) {
    return <p className="muted" role="status">{t("health.loading")}</p>;
  }
  if (isError) {
    return <p className="alert" role="alert">{t("health.unreachable")}</p>;
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
      <PageHead id="health-title" title={t("health.title")} lead={t("health.intro")} />
      <div className="card">
        <p className={data.status === "ok" ? "notice" : "alert"} role={data.status === "ok" ? "status" : "alert"}>
          {t(data.status === "ok" ? "health.ok" : "health.degraded")}
        </p>
        <ul className="checks">
          <li className={data.database === "up" ? "ok" : "ko"}>
            {t(data.database === "up" ? "health.databaseUp" : "health.databaseDown")}
          </li>
          <li className={data.schema_version === data.expected_schema_version ? "ok" : "ko"}>{schema}</li>
        </ul>
      </div>
    </section>
  );
}
