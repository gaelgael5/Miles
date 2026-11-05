import { type KeyboardEvent, type ReactNode, useId, useRef } from "react";

/**
 * Une barre d'onglets et le panneau de l'onglet courant (Gael, 04/11/2026 sur les
 * sources d'ingestion, 05/11/2026 sur un modèle de données).
 *
 * Au socle au DEUXIÈME usage, comme le reste : la feuille du socle dessinait déjà
 * `.tabs` et `.tab`, et c'est le câblage ARIA — rôles, `aria-selected`, `aria-controls`,
 * tabulation unique et flèches — qui aurait été recopié. Un motif d'accessibilité
 * recopié diverge au premier correctif fait d'un seul côté, et la divergence ne se voit
 * dans aucune capture d'écran.
 *
 * La barre ET le panneau sont rendus ici : les identifiants qui les lient ne sortent
 * donc jamais du composant. Les laisser composer par l'appelant, c'était lui confier
 * deux chaînes à garder d'accord, que rien ne vérifie au type.
 *
 * Le CONTENU du panneau reste à l'appelant : c'est lui qui sait quoi monter, et quoi
 * remonter — un journal qui garde sa page courante quand la source change, par exemple.
 */
export function Tabs<T extends string>({
  label,
  tabs,
  current,
  onSelect,
  children,
}: {
  /** Nom de la barre pour un lecteur d'écran : plusieurs barres peuvent coexister. */
  label: string;
  tabs: readonly { readonly name: T; readonly label: string }[];
  current: T;
  onSelect: (name: T) => void;
  children: ReactNode;
}) {
  // `useId` plutôt que le nom de l'onglet : deux barres de la même page porteraient
  // sinon les mêmes identifiants, et `aria-controls` ne désignerait plus rien de sûr.
  const prefixe = useId();
  const boutons = useRef<Partial<Record<T, HTMLButtonElement | null>>>({});
  const tabId = (nom: T) => `${prefixe}-tab-${nom}`;
  const panelId = (nom: T) => `${prefixe}-panel-${nom}`;

  function auClavier(evenement: KeyboardEvent, rang: number) {
    const pas = evenement.key === "ArrowRight" ? 1 : evenement.key === "ArrowLeft" ? -1 : 0;
    if (pas === 0) {
      return;
    }
    evenement.preventDefault();
    // `?? current` pour `noUncheckedIndexedAccess` : l'index est déjà ramené dans les
    // bornes par le modulo, et ce repli ne peut pas se produire.
    const suivant = tabs[(rang + pas + tabs.length) % tabs.length]?.name ?? current;
    onSelect(suivant);
    boutons.current[suivant]?.focus();
  }

  return (
    <>
      <div className="tabs" role="tablist" aria-label={label}>
        {tabs.map((onglet, rang) => (
          <button
            key={onglet.name}
            type="button"
            role="tab"
            id={tabId(onglet.name)}
            className="tab"
            aria-selected={current === onglet.name}
            aria-controls={panelId(onglet.name)}
            // Une seule entrée au clavier dans la barre, et les flèches pour changer
            // d'onglet : c'est le motif ARIA des onglets. Sans lui, la tabulation
            // traverse chaque onglet avant d'atteindre le contenu — souvent un
            // formulaire qu'on remplit, pas une page qu'on survole.
            tabIndex={current === onglet.name ? 0 : -1}
            ref={(noeud) => {
              boutons.current[onglet.name] = noeud;
            }}
            onKeyDown={(evenement) => auClavier(evenement, rang)}
            onClick={() => onSelect(onglet.name)}
          >
            {onglet.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={panelId(current)} aria-labelledby={tabId(current)}>
        {children}
      </div>
    </>
  );
}
