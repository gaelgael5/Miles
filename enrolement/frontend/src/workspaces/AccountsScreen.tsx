import { useTranslation } from "react-i18next";

import { PageHead } from "@miles/socle-web";

import type { Environment } from "../api/environments";

/**
 * Les comptes d'un workspace hébergé — la PAGE, et rien d'autre pour l'instant.
 *
 * Demandé ainsi par Gael le 01/11/2026 : « pour le moment tu ne fais qu'afficher la page
 * parce que le stockage des comptes se fera sur l'environnement et nous exposera des api
 * de recherche et d'exposition avec pagination ». Les comptes ne sont donc PAS ici : ils
 * vivront sur la stack d'environnement, et cette page les lira par ses routes quand elles
 * existeront. Ne rien afficher est exact ; afficher une liste vide ne le serait pas.
 */
export function AccountsScreen({ environnement }: { environnement: Environment }) {
  const { t } = useTranslation();

  return (
    <section className="section" aria-labelledby="accounts-title">
      <PageHead
        id="accounts-title"
        title={t("workspaces.accounts.title")}
        lead={t("workspaces.accounts.lead", {
          workspace: environnement.workspace_id,
          label: environnement.label,
        })}
      />
      <div className="card">
        <p className="alert" role="status">
          {t("workspaces.accounts.pending")}
        </p>
      </div>
    </section>
  );
}
