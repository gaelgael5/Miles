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
 * **Tout vient du contrat PUBLIÉ**, lu à l'ouverture — en-têtes, types de contenu, corps
 * attendu, réponses et leurs formes. Rien n'est recopié ici : un en-tête ajouté ou un
 * refus de plus apparaît sans qu'on touche à ce composant, et c'est la seule façon qu'une
 * page de contrat ne mente pas sur le contrat.
 *
 * Le schéma du corps montré est celui du MODÈLE D'ENTRÉE de la source — résolu contre la
 * version servie —, et non le schéma générique du contrat : c'est celui-là que la
 * validation emploiera, et c'est lui qu'un intégrateur doit respecter.
 */
export function MethodSignature({
  method,
  signature,
}: {
  method: Method;
  signature: Signature | undefined;
}) {
  if (signature === undefined) {
    // Le contrat n'a pas pu être lu : la méthode reste essayable, mais on ne prétend pas
    // montrer une signature qu'on n'a pas.
    return null;
  }
  return (
    <div className="card-inset">
      {signature.description !== "" && <p className="help">{signature.description}</p>}
      <Headers signature={signature} />
      <Body method={method} signature={signature} />
      <Responses signature={signature} />
    </div>
  );
}

function Headers({ signature }: { signature: Signature }) {
  const { t } = useTranslation();

  if (signature.parameters.length === 0) {
    return null;
  }
  return (
    <section>
      <h4>{t("ingestion.signature.headers")}</h4>
      <ul className="plain-list">
        {signature.parameters.map((parametre) => (
          <li key={parametre.name} className="row">
            <div className="row-main">
              <span className="row-title mono">{parametre.name}</span>
              <div className="row-sub">
                {parametre.required
                  ? t("ingestion.signature.required")
                  : t("ingestion.signature.optional")}
                {parametre.description !== "" && ` · ${parametre.description}`}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Le corps attendu : ses types de contenu, et sa forme.
 *
 * Les deux schémas sont montrés, et ce n'est pas une redondance : celui du CONTRAT dit ce
 * que l'adresse accepte quel que soit le paramétrage — un objet, un tableau, un document
 * —, celui du MODÈLE dit ce que cette entrée de source valide. Un intégrateur a besoin des
 * deux : le premier pour construire son appel, le second pour construire ses données.
 */
function Body({ method, signature }: { method: Method; signature: Signature }) {
  const { t } = useTranslation();

  if (signature.body.length === 0) {
    return null;
  }
  return (
    <section>
      <h4>{t("ingestion.signature.body")}</h4>
      {signature.bodyDescription !== "" && <p className="help">{signature.bodyDescription}</p>}
      <p className="caption">
        {t("ingestion.signature.contentTypes")}{" "}
        {signature.body.map((media) => media.contentType).join(", ")}
      </p>
      {method.request_schema !== null && (
        <details>
          <summary>
            {t("ingestion.signature.modelSchema", { model: method.entry_model })}
          </summary>
          <pre className="mono">{JSON.stringify(method.request_schema, null, 2)}</pre>
        </details>
      )}
      <details>
        <summary>{t("ingestion.signature.contractSchema")}</summary>
        <pre className="mono">
          {JSON.stringify(
            signature.body.map((media) => ({ [media.contentType]: media.schema })),
            null,
            2,
          )}
        </pre>
      </details>
    </section>
  );
}

/**
 * Les réponses déclarées, avec leur forme.
 *
 * Par MÉTHODE et non une fois pour la page : le mode fichier rend 202 et un accusé sans
 * compte-rendu, les deux autres rendent 201 et le sort de chaque objet. Les mélanger
 * ferait promettre à l'un ce que l'autre tient.
 */
function Responses({ signature }: { signature: Signature }) {
  const { t } = useTranslation();

  return (
    <section>
      <h4>{t("ingestion.signature.responses")}</h4>
      <ul className="plain-list">
        {signature.responses.map((reponse) => (
          <li key={reponse.status} className="row">
            <div className="row-main">
              <span className="row-title mono">{reponse.status}</span>
              <div className="row-sub">{reponse.description}</div>
              {reponse.schema !== null && (
                <details>
                  <summary>{t("ingestion.signature.shape")}</summary>
                  <pre className="mono">{JSON.stringify(reponse.schema, null, 2)}</pre>
                </details>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
