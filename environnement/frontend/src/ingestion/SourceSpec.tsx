import { Suspense, lazy } from "react";
import { useTranslation } from "react-i18next";

import { CollapsibleSpec } from "@miles/socle-web";

import { ContractGate } from "./ContractGate";

// Chargé à l'ouverture de l'onglet seulement : le bundle Swagger pèse plus que tout le
// reste de l'application, et la plupart des visites n'y passent jamais. Son propre onglet
// rend cette paresse réellement payante — avant, il partait dès qu'on ouvrait une source.
const SwaggerView = lazy(() => import("./SwaggerView"));

/**
 * Le contrat de la source dans un visualiseur Swagger standard (Gael, 04/11/2026).
 *
 * Standard, et non une présentation maison : c'est l'outil que l'intégrateur connaît
 * déjà, celui dont il attend les schémas dépliables et le document brut. Le nôtre les
 * montrait aussi, mais il nous aurait fallu suivre OpenAPI à la main pour chaque forme
 * qu'un contrat peut prendre.
 *
 * Ce qui lui est donné n'est pas le contrat publié tel quel : c'est sa restriction à
 * CETTE source, adresses réelles comprises. Spécialisé PAR LE SERVEUR depuis le
 * 05/11/2026 : la même adresse sert l'écran et l'intégrateur qui la télécharge, donc ce
 * qu'on regarde et ce qu'on publie ne peuvent plus différer.
 *
 * **Onglet à part depuis le 07/11/2026**, et sa description arrive REPLIÉE à chaque
 * chargement : la même prose d'en-tête coiffe le contrat de toutes les sources.
 */
export function SourceSpec({ source }: { source: string }) {
  const { t } = useTranslation();

  return (
    <ContractGate source={source}>
      {(spec) => (
        <CollapsibleSpec>
          <Suspense
            fallback={
              <p className="muted" role="status">
                {t("ingestion.contract.loading")}
              </p>
            }
          >
            <SwaggerView spec={spec} />
          </Suspense>
        </CollapsibleSpec>
      )}
    </ContractGate>
  );
}
