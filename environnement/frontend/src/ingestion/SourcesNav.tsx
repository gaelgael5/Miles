import { useIngestionHealth } from "../api/ingestion";

/**
 * Les sources servies, en sous-menu du service d'ingestion (Gael, 04/11/2026).
 *
 * Elles viennent de l'ÉTAT du service, donc de la version servie, et jamais d'une liste
 * tenue ici : une source apparaît dans le menu le jour où la stack sert la version qui la
 * déclare, et en disparaît le jour où la suivante ne la déclare plus. Une liste écrite à
 * la main aurait promis des pages vides et caché les sources neuves.
 *
 * Même requête que la page du service : TanStack Query la partage par sa clé, donc ouvrir
 * le menu n'ajoute pas d'appel à l'ouverture de l'écran.
 */
export function SourcesNav({
  selected,
  onOpen,
}: {
  selected: string | null;
  onOpen: (source: string) => void;
}) {
  const health = useIngestionHealth();
  // Dédoublonnées : une source a un point d'entrée par MODE, et le menu nomme la source.
  // Triées pour que l'ordre du menu ne dépende pas de celui des fichiers du dépôt.
  const sources = [...new Set((health.data?.endpoints ?? []).map((point) => point.source))].sort();

  // État illisible ou version non servie : aucun sous-menu, et AUCUNE alerte ici. Un menu
  // qui crie n'apprend rien — c'est la page du service qui dit pourquoi elle est vide, et
  // c'est elle qu'on ouvre en cliquant sur l'entrée au-dessus.
  return (
    <>
      {sources.map((source) => (
        <button
          key={source}
          type="button"
          className="sidebar-link sidebar-sublink"
          aria-current={selected === source ? "page" : undefined}
          onClick={() => onOpen(source)}
        >
          {source}
        </button>
      ))}
    </>
  );
}
