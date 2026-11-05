import { useTranslation } from "react-i18next";

import { CopyButton } from "./CopyButton";

/**
 * L'adresse d'un contrat, à copier ou à télécharger (Gael, 05/11/2026).
 *
 * Au socle dès le premier jour, parce que les deux produits qui montrent un contrat
 * l'ajoutent dans le même geste : le portail pour ses contrats et ses sources, le module
 * d'environnement pour l'API de chacune de ses sources. Deux blocs recopiés auraient
 * divergé sur ce qui compte ici — le fait de DIRE que l'adresse s'ouvre sans compte.
 *
 * Le téléchargement est un lien vers cette même adresse, et non un document rebâti dans
 * le navigateur : ce qu'on enregistre est alors exactement ce qu'un appel rend, et il
 * n'y a pas deux chemins par lesquels le contrat peut sortir.
 */
export function ContractAddress({ url, filename }: { url: string; filename: string }) {
  const { t } = useTranslation();
  return (
    <section className="panel contract-address" aria-label={t("contract.address")}>
      <p className="caption">{t("contract.address")}</p>
      <p className="mono contract-url">{url}</p>
      <div className="actions">
        {/* `download` porte le nom du fichier enregistré : sans lui, le navigateur
            propose « contract » ou le dernier segment de l'adresse, et l'intégrateur
            se retrouve avec trois fichiers de même nom. */}
        <a className="btn btn-secondary" href={url} download={filename}>
          {t("contract.download")}
        </a>
        <CopyButton text={url} label={t("contract.copy")} />
      </div>
      <p className="help">{t("contract.public")}</p>
    </section>
  );
}
