import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Tabs } from "@miles/socle-web";
import { IngestionCalls } from "./IngestionCalls";
import { IngestionMethods } from "./IngestionMethods";
import { SourceContract } from "./SourceContract";

/**
 * Les trois vues d'une source, dans l'ordre où on s'en sert : le CONTRAT qu'elle promet,
 * l'ESSAI qui le vérifie, puis ce qu'elle a REÇU. On branche une intégration avant
 * d'avoir des appels à lire, et une page qui s'ouvrirait sur un journal vide n'aurait
 * rien à dire le premier jour.
 *
 * L'essai est à part du contrat parce que le contrat est rendu par un composant Swagger
 * standard, dont le « Try it out » ne peut pas servir : il partirait sans clé d'API.
 */
const ONGLETS = ["contract", "trial", "calls"] as const;
type Onglet = (typeof ONGLETS)[number];

/**
 * Une source d'ingestion, page à part (Gael, 04/11/2026) : son contrat, son essai, ses logs.
 *
 * La page du service listait les méthodes de TOUTES les sources et un journal commun
 * filtrable. Le partenaire qu'on équipe, lui, n'en intègre qu'UNE : il lui faut ses
 * adresses, ses signatures et ses propres dépôts, pas ceux des autres. D'où la source en
 * entrée de menu, et deux onglets plutôt qu'une page qui empile tout.
 *
 * Le filtre par source du journal disparaît avec ce découpage : le menu le porte
 * désormais, et deux façons de choisir la même chose auraient divergé — une source
 * choisie dans le filtre n'aurait pas été celle que le menu montre comme courante.
 */
export function SourceScreen({ source }: { source: string }) {
  const { t } = useTranslation();
  const [onglet, setOnglet] = useState<Onglet>("contract");

  return (
    <section aria-labelledby="ingestion-source-title">
      <div className="page-head">
        <div>
          <h1 id="ingestion-source-title">{source}</h1>
          <p className="lead">{t("ingestion.source.intro")}</p>
        </div>
      </div>
      <Tabs
        label={t("ingestion.source.tabs")}
        tabs={ONGLETS.map((nom) => ({ name: nom, label: t(`ingestion.source.${nom}`) }))}
        current={onglet}
        onSelect={setOnglet}
      >
        {onglet === "contract" ? (
          <SourceContract source={source} />
        ) : onglet === "trial" ? (
          <IngestionMethods source={source} />
        ) : (
          // Remonté quand la source change : le journal garde sa page courante, et
          // rester en page 3 d'une source qui n'en a qu'une afficherait un vide qu'on
          // lirait comme « ce partenaire n'a rien déposé ».
          <IngestionCalls key={source} source={source} />
        )}
      </Tabs>
    </section>
  );
}
