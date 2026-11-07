import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@miles/socle-web";

import { useIngestionContract } from "../api/ingestion";

/**
 * Les trois états d'un contrat de source, tenus EN UN SEUL endroit.
 *
 * Deux onglets lisent le même document depuis le 07/11/2026 — celui des adresses et
 * celui du visualiseur Swagger —, et ils doivent dire la même chose quand il manque. Deux
 * jeux de branches auraient divergé au premier message retouché, et l'un des deux onglets
 * aurait annoncé une source servie que l'autre déclare absente.
 *
 * La requête elle-même n'est pas doublée : elle est mise en cache par sa clé, donc le
 * second onglet lit ce que le premier a déjà demandé.
 */
export function ContractGate({
  source,
  children,
}: {
  source: string;
  children: (spec: object) => ReactNode;
}) {
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
  return <>{children(spec)}</>;
}
