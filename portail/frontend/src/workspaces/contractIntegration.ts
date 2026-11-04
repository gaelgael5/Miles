import { useState } from "react";

import { useImportVersion, usePreviewContract } from "../api/contracts";
import type { WorkTarget } from "../api/workTarget";

/**
 * L'intégration d'un fichier de contrat, tenue par l'écran plutôt que par son bloc : le
 * bouton « Intégrer » et Ctrl+S vivent dans l'en-tête de la page (story caad743d).
 */
export function useIntegration(
  target: WorkTarget,
  slug: string,
  onIntegrated: (number: number) => void,
) {
  const preview = usePreviewContract(target);
  const save = useImportVersion(target, slug);
  const [content, setContent] = useState("");
  // Lu = l'aperçu porte sur le texte affiché. Modifié depuis, il se relit avant d'être
  // intégré : on n'intègre jamais un texte dont on n'a pas vu ce qu'il contient.
  const read = preview.variables === content ? (preview.data ?? null) : null;

  function load(text: string) {
    setContent(text);
    save.reset();
    preview.mutate(text);
  }

  function readContent() {
    save.reset();
    preview.mutate(content);
  }

  function clear() {
    setContent("");
    preview.reset();
    save.reset();
  }

  function integrate() {
    save.mutate(content, {
      onSuccess: (version) => {
        clear();
        onIntegrated(version.number);
      },
    });
  }

  const busy = preview.isPending || save.isPending;
  // Ctrl+S (Gael, 23/10/2026) : intègre un texte lu, sinon le lit d'abord.
  function shortcut() {
    if (busy) return;
    if (read) integrate();
    else if (content.trim()) readContent();
  }

  return { preview, save, content, setContent, read, busy, load, readContent, clear, integrate, shortcut };
}

export type Integration = ReturnType<typeof useIntegration>;
