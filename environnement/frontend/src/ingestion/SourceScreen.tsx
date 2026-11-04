import { type KeyboardEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

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

const tabId = (onglet: Onglet) => `ingestion-source-tab-${onglet}`;
const panelId = (onglet: Onglet) => `ingestion-source-panel-${onglet}`;

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
  const boutons = useRef<Partial<Record<Onglet, HTMLButtonElement | null>>>({});

  function auClavier(evenement: KeyboardEvent, rang: number) {
    const pas = evenement.key === "ArrowRight" ? 1 : evenement.key === "ArrowLeft" ? -1 : 0;
    if (pas === 0) {
      return;
    }
    evenement.preventDefault();
    // `?? onglet` pour `noUncheckedIndexedAccess` : l'index est déjà ramené dans les
    // bornes par le modulo, et ce repli ne peut pas se produire.
    const suivant = ONGLETS[(rang + pas + ONGLETS.length) % ONGLETS.length] ?? onglet;
    setOnglet(suivant);
    boutons.current[suivant]?.focus();
  }

  return (
    <section aria-labelledby="ingestion-source-title">
      <div className="page-head">
        <div>
          <h1 id="ingestion-source-title">{source}</h1>
          <p className="lead">{t("ingestion.source.intro")}</p>
        </div>
      </div>
      <div className="tabs" role="tablist" aria-label={t("ingestion.source.tabs")}>
        {ONGLETS.map((nom, rang) => (
          <button
            key={nom}
            type="button"
            role="tab"
            id={tabId(nom)}
            className="tab"
            aria-selected={onglet === nom}
            aria-controls={panelId(nom)}
            // Une seule entrée au clavier dans la barre, et les flèches pour changer
            // d'onglet : c'est le motif ARIA des onglets. Sans lui, la tabulation
            // traverse chaque onglet avant d'atteindre le contenu — ici des formulaires
            // d'essai qu'on remplit, pas une page qu'on survole.
            tabIndex={onglet === nom ? 0 : -1}
            ref={(noeud) => {
              boutons.current[nom] = noeud;
            }}
            onKeyDown={(evenement) => auClavier(evenement, rang)}
            onClick={() => setOnglet(nom)}
          >
            {t(`ingestion.source.${nom}`)}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={panelId(onglet)} aria-labelledby={tabId(onglet)}>
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
      </div>
    </section>
  );
}
