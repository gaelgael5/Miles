import { useStorages } from "../api/storages";

/**
 * Les espaces de stockage de la version servie, en sous-menu (Gael, 04/11/2026).
 *
 * Mêmes règles que les sources d'ingestion : la liste vient de la VERSION SERVIE, jamais
 * d'une liste tenue ici — un espace apparaît le jour où la version qui le déclare est
 * servie, et disparaît quand la suivante ne le déclare plus.
 *
 * Les espaces REFUSÉS y figurent comme les autres : les écarter du menu ferait chercher
 * une déclaration absente alors qu'elle est là, et fautive. Leur page dit pourquoi.
 *
 * Même requête que la page des espaces : TanStack Query la partage par sa clé, donc le
 * menu n'ajoute aucun appel.
 */
export function StoragesNav({
  selected,
  onOpen,
}: {
  selected: string | null;
  onOpen: (name: string) => void;
}) {
  const storages = useStorages();

  return (
    <>
      {(storages.data ?? []).map((storage) => (
        <button
          key={storage.name}
          type="button"
          className="sidebar-link sidebar-sublink"
          aria-current={selected === storage.name ? "page" : undefined}
          onClick={() => onOpen(storage.name)}
        >
          {storage.label}
        </button>
      ))}
    </>
  );
}
