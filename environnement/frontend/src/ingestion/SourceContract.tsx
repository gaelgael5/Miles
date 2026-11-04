import { Suspense, lazy, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { useIngestionContract, useIngestionMethods } from "../api/ingestion";
import { sourceSpecOf } from "./sourceSpec";

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
 * CETTE source, adresses réelles comprises (voir `sourceSpec`).
 */
export function SourceContract({ source }: { source: string }) {
  const { t } = useTranslation();
  const methods = useIngestionMethods();
  const contract = useIngestionContract();
  const spec = useMemo(
    () =>
      contract.data === undefined || methods.data === undefined
        ? undefined
        : sourceSpecOf(contract.data, methods.data.methods, source),
    [contract.data, methods.data, source],
  );

  if (contract.isPending || methods.isPending) {
    return (
      <p className="muted" role="status">
        {t("ingestion.contract.loading")}
      </p>
    );
  }
  if (spec === undefined) {
    // Le contrat ou les méthodes n'ont pas pu être lus : on ne montre pas un contrat
    // amputé, qui se lirait comme « cette source n'expose que ça ».
    return (
      <p className="alert" role="alert">
        {t("ingestion.contract.unreadable")}
      </p>
    );
  }
  if (Object.keys(spec.paths as object).length === 0) {
    // L'état normal d'une source dont la version servie ne déclare aucune entrée, et non
    // une panne : Swagger rendrait une page vide sans rien en dire.
    return <p className="help">{t("ingestion.methods.none")}</p>;
  }
  return (
    <Suspense
      fallback={
        <p className="muted" role="status">
          {t("ingestion.contract.loading")}
        </p>
      }
    >
      <SwaggerView spec={spec} />
    </Suspense>
  );
}
