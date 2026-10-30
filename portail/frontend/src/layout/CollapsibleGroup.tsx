import { type ReactNode, useId, useState } from "react";

/**
 * Un groupe du menu qu'on peut replier (Gael, 30/10/2026).
 *
 * TOUS les niveaux du menu le sont désormais, et pas seulement les deux sections du
 * haut : la barre compte une vingtaine d'entrées, et un niveau qu'on ne peut pas fermer
 * oblige à faire défiler pour atteindre ce qu'on cherche.
 *
 * L'état est LOCAL au groupe, pas tenu dans un registre partagé : rien n'a besoin de
 * savoir ce qu'un autre groupe fait, et un registre par titre confondrait deux groupes
 * homonymes de deux workspaces différents.
 */
export function CollapsibleGroup({
  label,
  className,
  defaultOpen = false,
  children,
}: {
  label: ReactNode;
  /** Classe du bouton : le niveau du menu décide de son allure. */
  className: string;
  /** Replié par défaut (Gael, 30/10/2026) : la barre compte une vingtaine d'entrées, et
   * tout ouvrir au chargement oblige à faire défiler pour atteindre ce qu'on cherche. */
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  // `useId` plutôt que le libellé : un libellé traduit ou répété donnerait deux éléments
  // du même identifiant, et `aria-controls` ne désignerait plus rien de sûr.
  const id = useId();
  return (
    <>
      <button
        type="button"
        className={className}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((ouvert) => !ouvert)}
      >
        {label}
      </button>
      <div id={id} hidden={!open}>
        {children}
      </div>
    </>
  );
}
