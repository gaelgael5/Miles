import { useTranslation } from "react-i18next";

import type { Method, Signature } from "../api/ingestion";

/**
 * La SIGNATURE d'une méthode : de quoi préparer une intégration sans l'essayer.
 *
 * Décision de Gael du 04/11/2026, après avoir vu une page qui ne savait qu'essayer :
 * « je t'ai demandé une page swagger. L'intérêt, c'est qu'en plus du test, il y a aussi
 * les signatures pour tester et faire l'intégration, et la description des contrats pour
 * faire les connexions en amont. » L'essai est le bonus ; la signature est la page.
 *
 * **Compacte, et c'est une correction du même jour** — « la présentation de la page est
 * trop chargée ». D'où la forme retenue : une LIGNE par chose (en-têtes, corps, codes de
 * réponse), et le détail — schémas, descriptions de chaque réponse — derrière deux replis.
 * Une page de référence se parcourt d'abord ; on ne déplie que ce qu'on cherche.
 *
 * **Tout vient du contrat PUBLIÉ**, lu à l'ouverture. Rien n'est recopié ici : un en-tête
 * ajouté ou un refus de plus apparaît sans qu'on touche à ce composant, et c'est la seule
 * façon qu'une page de contrat ne mente pas sur le contrat.
 */
export function MethodSignature({
  method,
  signature,
}: {
  method: Method;
  signature: Signature | undefined;
}) {
  const { t } = useTranslation();

  if (signature === undefined) {
    // Le contrat n'a pas pu être lu : la méthode reste essayable, mais on ne prétend pas
    // montrer une signature qu'on n'a pas.
    return null;
  }
  return (
    <>
      {signature.description !== "" && <p className="help">{signature.description}</p>}
      <dl className="caption">
        {signature.parameters.length > 0 && (
          <>
            <dt>{t("ingestion.signature.headers")}</dt>
            <dd className="mono">{signature.parameters.map(label(t)).join(" · ")}</dd>
          </>
        )}
        {signature.body.length > 0 && (
          <>
            <dt>{t("ingestion.signature.body")}</dt>
            <dd className="mono">
              {signature.body.map((media) => media.contentType).join(" · ")}
            </dd>
          </>
        )}
        <dt>{t("ingestion.signature.responses")}</dt>
        <dd className="mono">
          {signature.responses.map((reponse) => reponse.status).join(" · ")}
        </dd>
      </dl>
      <Schemas method={method} signature={signature} />
      <details>
        <summary>{t("ingestion.signature.responsesDetail")}</summary>
        <ul className="plain-list">
          {signature.responses.map((reponse) => (
            <li key={reponse.status} className="row">
              <div className="row-main">
                <span className="row-title mono">{reponse.status}</span>
                <div className="row-sub">{reponse.description}</div>
              </div>
            </li>
          ))}
        </ul>
      </details>
    </>
  );
}

/** Le libellé d'un en-tête : son nom, et s'il est exigé. La description est dans le repli. */
function label(t: (clef: string) => string) {
  return (parametre: { name: string; required: boolean }) =>
    `${parametre.name} (${
      parametre.required ? t("ingestion.signature.required") : t("ingestion.signature.optional")
    })`;
}

/**
 * Les deux schémas, derrière un seul repli.
 *
 * Les deux, et ce n'est pas une redondance : celui du MODÈLE dit ce que cette entrée de
 * source valide — c'est lui qu'un intégrateur doit respecter —, celui du CONTRAT dit ce
 * que l'adresse accepte quel que soit le paramétrage. Un seul repli pour les deux, parce
 * qu'on les ouvre au même moment : quand on écrit le code qui appelle.
 */
function Schemas({ method, signature }: { method: Method; signature: Signature }) {
  const { t } = useTranslation();

  return (
    <details>
      <summary>{t("ingestion.signature.schemas")}</summary>
      {method.request_schema !== null && (
        <>
          <p className="caption">
            {t("ingestion.signature.modelSchema", { model: method.entry_model })}
          </p>
          <pre className="mono">{JSON.stringify(method.request_schema, null, 2)}</pre>
        </>
      )}
      <p className="caption">{t("ingestion.signature.contractSchema")}</p>
      <pre className="mono">
        {JSON.stringify(
          Object.fromEntries(signature.body.map((media) => [media.contentType, media.schema])),
          null,
          2,
        )}
      </pre>
      {signature.responses
        .filter((reponse) => reponse.schema !== null)
        .map((reponse) => (
          <div key={reponse.status}>
            <p className="caption">
              {t("ingestion.signature.shape", { status: reponse.status })}
            </p>
            <pre className="mono">{JSON.stringify(reponse.schema, null, 2)}</pre>
          </div>
        ))}
    </details>
  );
}
