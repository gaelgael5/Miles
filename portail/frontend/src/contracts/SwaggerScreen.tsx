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

/** Le nom du fichier enregistré : celui du sujet, pas « openapi » pour tous. */
function fileOf(subject: SwaggerSubject): string {
  return subject.kind === "contract"
    ? `${subject.slug}-v${subject.version}.openapi.json`
    : `${subject.name}.openapi.json`;
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
      <div className="page-head">
        <h1 id="swagger-title">{title}</h1>
        {/* Télécharger le document, d'un clic (Gael, 05/11/2026) : un lien vers la MÊME
            adresse que l'écran lit, et non un document rebâti dans le navigateur — ce
            qu'on enregistre est alors exactement ce qu'un appel rend.
            L'adresse demande une session, à la différence du contrat d'ingestion d'un
            environnement : ici le document se lit dans une BRANCHE du paramétrage, et
            l'ouvrir à tous demanderait de le publier ailleurs que derrière un checkout
            git — ce qui reste à faire. */}
        <a
          className="btn btn-secondary"
          href={addressOf(target, subject)}
          download={fileOf(subject)}
        >
          {t("contract.download")}
        </a>
      </div>
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
