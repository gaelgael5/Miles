import { Suspense, lazy } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, ContractAddress } from "@miles/socle-web";
import { contractUrl, useIngestionContract } from "../api/ingestion";

// Chargé à l'ouverture de l'onglet seulement : le bundle Swagger pèse plus que tout le
// reste de l'application, et la plupart des visites n'y passent jamais.
const SwaggerView = lazy(() => import("./SwaggerView"));

/**
 * Le contrat de la source, dans un visualiseur Swagger standard (Gael, 04/11/2026).
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
 */
export function SourceContract({ source }: { source: string }) {
  const { t } = useTranslation();
  const contract = useIngestionContract(source);
  const spec = contract.data;

  if (contract.isPending) {
    return (
      <p className="muted" role="status">
        {t("ingestion.contract.loading")}
      </p>
    );
  }
  if (contract.error instanceof ApiError && contract.error.status === 404) {
    // L'état normal d'une source dont la version servie ne déclare aucune entrée, et non
    // une panne : le serveur refuse de rendre un contrat sans chemin, qui se lirait
    // « cette source n'expose rien » alors qu'elle n'est pas servie du tout.
    return <p className="help">{t("ingestion.methods.none")}</p>;
  }
  if (spec === undefined) {
    // Le contrat n'a pas pu être lu : on ne montre pas un contrat amputé, qui se lirait
    // comme « cette source n'expose que ça ».
    return (
      <p className="alert" role="alert">
        {t("ingestion.contract.unreadable")}
      </p>
    );
  }
  return (
    <>
      <ContractAddress url={contractUrl(source)} filename={`${source}.openapi.json`} />
      <Suspense
        fallback={
          <p className="muted" role="status">
            {t("ingestion.contract.loading")}
          </p>
        }
      >
        <SwaggerView spec={spec} />
      </Suspense>
    </>
  );
}
