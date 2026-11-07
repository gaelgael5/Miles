import { type ReactNode, useId, useState } from "react";
import { useTranslation } from "react-i18next";

/**
 * Le visualiseur d'un contrat, dont la DESCRIPTION se replie.
 *
 * Ce qui se replie est le message d'en-tête du document — quatre cents pixels de prose
 * sur la page d'ingestion —, pas le contrat : les adresses, leurs refus et les schémas
 * restent là. Replier le tout aurait fait un écran qui ne montre plus rien, alors que
 * c'est la redite qu'on veut retirer : la même description est en tête de CHAQUE source.
 *
 * **Replié à CHAQUE chargement de page, et le choix n'est plus mémorisé** (Gael,
 * 07/11/2026 : « au chargement de la page peux-tu collapser le bloc »). C'est un
 * renversement assumé de sa décision du 05/11, qui gardait le dépliement d'une page à
 * l'autre comme le menu latéral : en pratique, la page revenait dépliée sans qu'on
 * comprenne pourquoi, et le repli n'était plus un défaut mais un souvenir. Qui veut lire
 * la description la déplie, pour cette page-là.
 *
 * Le repli est obtenu par une CLASSE, pas en touchant au DOM de Swagger UI : il le
 * reconstruit à chaque changement de document, et tout nœud qu'on lui aurait caché
 * serait revenu visible sans prévenir.
 */
export function CollapsibleSpec({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [folded, setFolded] = useState(true);
  const id = useId();

  return (
    <>
      {/* Un chevron, pas un bouton (Gael, 05/11/2026) : le geste est secondaire, et un
          bouton plein pesait plus lourd que le titre qu'il découvre. Son nom est porté
          par `aria-label` et répété en infobulle — une flèche seule ne dit rien à qui
          ne l'a jamais cliquée. */}
      <button
        type="button"
        className="spec-toggle"
        aria-expanded={!folded}
        aria-controls={id}
        aria-label={t(folded ? "contract.showDescription" : "contract.hideDescription")}
        title={t(folded ? "contract.showDescription" : "contract.hideDescription")}
        onClick={() => setFolded((replie) => !replie)}
      />
      <div id={id} className={folded ? "spec-host spec-folded" : "spec-host"}>
        {children}
      </div>
    </>
  );
}
