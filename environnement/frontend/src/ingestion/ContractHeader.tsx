import { useTranslation } from "react-i18next";

import type { Contract } from "../api/ingestion";

/**
 * Ce que le contrat dit de LUI-MÊME, en tête de la page de service.
 *
 * Ce qu'un intégrateur lit AVANT d'appeler quoi que ce soit (Gael, 04/11/2026) : comment
 * s'authentifier, ce que l'idempotence garantit, ce que les modes changent, et ce que
 * l'écriture différentielle promet. C'est la partie « connexions en amont » : elle se
 * prépare sans accès et sans essai.
 *
 * **La description vient du contrat publié**, pas de cette page. Elle est engendrée par la
 * même fonction que le fichier versionné : deux textes auraient divergé, et le second
 * aurait été celui que personne ne régénère.
 */
export function ContractHeader({ contract }: { contract: Contract }) {
  const { t } = useTranslation();

  return (
    <details className="card">
      <summary>{t("ingestion.contract.title", { version: contract.version })}</summary>
      {/* Les paragraphes du contrat, séparés comme il les sépare. Le Markdown n'est pas
          interprété : un contrat se lit, et faire entrer un rendu Markdown ici ferait
          entrer une dépendance pour mettre trois mots en gras. */}
      {contract.description.split("\n\n").map((paragraphe, rang) => (
        <p key={rang} className="help">
          {paragraphe}
        </p>
      ))}
      <Authentications contract={contract} />
      <details>
        <summary>{t("ingestion.contract.spec")}</summary>
        <p className="help">{t("ingestion.contract.specHelp")}</p>
        <pre className="mono">{JSON.stringify(contract.spec, null, 2)}</pre>
      </details>
    </details>
  );
}

/**
 * Les façons de s'authentifier, telles que le contrat les déclare.
 *
 * Déclarées en schémas de sécurité et non racontées : c'est ce qu'un client engendré lit.
 * La page les montre pour que l'intégrateur sache quel en-tête poser avant d'écrire une
 * seule ligne.
 */
function Authentications({ contract }: { contract: Contract }) {
  const { t } = useTranslation();

  if (contract.security.length === 0) {
    return null;
  }
  return (
    <section>
      <h4>{t("ingestion.contract.auth")}</h4>
      <ul className="plain-list">
        {contract.security.map((scheme) => (
          <li key={scheme.name} className="row">
            <div className="row-main">
              <span className="row-title mono">
                {scheme.header !== "" ? scheme.header : "Authorization: Bearer"}
              </span>
              <div className="row-sub">{scheme.description}</div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
