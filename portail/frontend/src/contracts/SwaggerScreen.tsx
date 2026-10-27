import { Suspense, lazy } from "react";
import { useTranslation } from "react-i18next";

import { useQuery } from "@tanstack/react-query";

import { request } from "@miles/socle-web";
import { type WorkTarget, atBranch, branchKey } from "../api/workTarget";

const SwaggerView = lazy(() => import("./SwaggerView"));

/** Ce qu'on affiche : une version de contrat, ou l'API qu'une source promet. */
export type SwaggerSubject =
  | { kind: "contract"; slug: string; version: number }
  | { kind: "source"; name: string };

function addressOf(target: WorkTarget, subject: SwaggerSubject): string {
  if (subject.kind === "contract") {
    return atBranch(
      target,
      "contracts",
      subject.slug,
      "versions",
      String(subject.version),
      "openapi",
    );
  }
  return atBranch(target, "sources", subject.name, "openapi");
}

function keyOf(target: WorkTarget, subject: SwaggerSubject) {
  return subject.kind === "contract"
    ? [...branchKey("openapi", target), "contract", subject.slug, subject.version]
    : [...branchKey("openapi", target), "source", subject.name];
}

/** Une version de contrat, ou l'API d'une source, lue en Swagger. */
export function SwaggerScreen({
  target,
  subject,
  title,
  onBack,
}: {
  target: WorkTarget;
  subject: SwaggerSubject;
  title: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const spec = useQuery({
    queryKey: keyOf(target, subject),
    queryFn: ({ signal }) => request<object>(addressOf(target, subject), { signal }),
  });

  return (
    <section aria-labelledby="swagger-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("swagger.back")}
      </button>
      <h1 id="swagger-title">{title}</h1>
      {spec.isPending && (
        <p className="muted" role="status">
          {t("dataModels.loading")}
        </p>
      )}
      {spec.isError && (
        <p className="alert" role="alert">
          {t("swagger.unreadable")}
        </p>
      )}
      {spec.data !== undefined && (
        <Suspense
          fallback={
            <p className="muted" role="status">
              {t("dataModels.loading")}
            </p>
          }
        >
          <SwaggerView spec={spec.data} />
        </Suspense>
      )}
    </section>
  );
}
