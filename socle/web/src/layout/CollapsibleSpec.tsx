import { type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";

const STORAGE_KEY = "miles.specDescriptionFolded";

/** Choix mémorisé sur ce navigateur ; le stockage peut être refusé (navigation privée). */
function readStored(): boolean {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function store(folded: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(folded));
  } catch {
    // Choix non mémorisé : il vaut pour cette page, et c'est un confort, pas un droit.
  }
}

/**
 * Le visualiseur d'un contrat, dont la DESCRIPTION se replie (Gael, 05/11/2026).
 *
 * Ce qui se replie est le message d'en-tête du document — quatre cents pixels de prose
 * sur la page d'ingestion —, pas le contrat : les adresses, leurs refus et les schémas
 * restent là. Replier le tout aurait fait un écran qui ne montre plus rien, alors que
 * c'est la redite qu'on veut retirer : la même description est en tête de CHAQUE source.
 *
 * Le repli est obtenu par une CLASSE, pas en touchant au DOM de Swagger UI : il le
 * reconstruit à chaque changement de document, et tout nœud qu'on lui aurait caché
 * serait revenu visible sans prévenir.
 *
 * Mémorisé d'une page à l'autre, comme le menu latéral : qui l'a replié une fois l'a lu,
 * et le rouvrir à chaque source défait le geste à chaque fois.
 */
export function CollapsibleSpec({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [folded, setFolded] = useState(readStored);
  const id = useId();

  return (
    <>
      <div className="actions spec-actions">
        <button
          type="button"
          className="btn btn-secondary"
          aria-expanded={!folded}
          aria-controls={id}
          onClick={() => {
            // Hors de la fonction de mise à jour : React peut l'appeler deux fois, et un
            // effet de bord n'y a rien à faire — même inoffensif, il apprend à en mettre.
            const suivant = !folded;
            setFolded(suivant);
            store(suivant);
          }}
        >
          {t(folded ? "contract.showDescription" : "contract.hideDescription")}
        </button>
      </div>
      <div id={id} className={folded ? "spec-host spec-folded" : "spec-host"}>
        {children}
      </div>
    </>
  );
}
