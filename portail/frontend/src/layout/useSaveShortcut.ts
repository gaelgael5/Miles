import { useEffect, useRef } from "react";

/**
 * Ctrl+S (⌘S sur Mac) déclenche l'enregistrement de l'écran (story caad743d). `save` vaut
 * null quand il n'y a rien à faire : la touche est alors sans effet.
 *
 * Écouté sur la fenêtre, en phase de capture : Monaco et les champs ne retiennent pas la
 * touche avant nous. L'enregistrement de page du navigateur est empêché même sans rien à
 * faire : sauver le HTML du portail ne servirait à personne et surprendrait.
 */
export function useSaveShortcut(save: (() => void) | null) {
  // La dernière version, sans réabonner l'écoute à chaque rendu.
  const latest = useRef(save);
  latest.current = save;

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "s") {
        event.preventDefault();
        latest.current?.();
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);
}
