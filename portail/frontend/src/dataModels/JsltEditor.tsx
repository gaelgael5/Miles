import { useEffect, useRef } from "react";

import { runsOn } from "./jsltKeys";

/** Assets du composant, servis par Miles lui-même (voir app.py), jamais par un CDN. */
const ASSETS = "/api/jslt-editor";
const CATALOG = "/api/jslt-functions";

/** Chargés une fois pour toute la page : le composant s'enregistre lui-même. */
let loading: Promise<void> | null = null;

function loadComponent(): Promise<void> {
  if (loading === null) {
    loading = new Promise<void>((resolve, reject) => {
      if (!document.querySelector(`link[href="${ASSETS}/jslt-editor.css"]`)) {
        const css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = `${ASSETS}/jslt-editor.css`;
        document.head.append(css);
      }
      const script = document.createElement("script");
      script.type = "module";
      script.src = `${ASSETS}/jslt-editor.js`;
      script.addEventListener("load", () => resolve());
      script.addEventListener("error", () => reject(new Error("jslt-editor introuvable")));
      document.head.append(script);
    });
  }
  return loading;
}

type EditorElement = HTMLElement & {
  value: string;
  // Présent à partir d'urban-json-editor 0.2.0, que Miles épingle. La garde reste : le
  // composant est servi par le backend, et une image en retard rendrait la 0.1.1, où
  // l'appel lèverait et emporterait l'éditeur entier plutôt que la seule complétion.
  setPaths?: (paths: unknown[]) => void;
};

/** Garde volontaire : sur la 0.1.1, `setPaths` n'existe pas et l'appel lèverait. */
function applyPaths(element: EditorElement, paths: unknown[] | undefined): void {
  if (paths !== undefined && typeof element.setPaths === "function") {
    element.setPaths(paths);
  }
}

/**
 * L'éditeur JSLT d'`urban-json-editor` (Gael, 24/10/2026) : coloration et auto-complétion
 * des fonctions, alimentée par le catalogue d'`urban-json` — donc par ce que la
 * transformation saura réellement exécuter.
 *
 * C'est un Web Component vanilla : React ne le rend pas, il l'héberge. D'où la ref, la
 * synchronisation de `value` à la main, et l'écoute de son événement `input`.
 *
 * Tab est géré par le composant lui-même (deux espaces, ou acceptation de la suggestion
 * quand l'auto-complétion est ouverte). F5 ne l'est pas : on l'ajoute ici.
 *
 * Les chemins du document source sont passés par `setPaths` (composant >= 0.2.0). La
 * garde porte bien sur `setPaths` et non sur la propriété `paths` : en 0.1.1, affecter
 * `paths` ne lèverait pas mais resterait sans effet — un test qui passe pour rien.
 */
export default function JsltEditor({
  value,
  onChange,
  onRun,
  readOnly,
  ariaLabel,
  paths,
}: {
  value: string;
  onChange: (value: string) => void;
  /** F5 : exécuter le template sans quitter le clavier. */
  onRun?: () => void;
  readOnly: boolean;
  ariaLabel: string;
  /** Chemins du modèle source, proposés sur « $ » et « @ » (composant >= 0.2.0). */
  paths?: unknown[];
}) {
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<EditorElement | null>(null);
  // Tenu dans une ref : l'écouteur du composant vit plus longtemps qu'un rendu, et
  // capturerait sinon la première version de la fonction.
  const changed = useRef(onChange);
  changed.current = onChange;
  const run = useRef(onRun);
  run.current = onRun;
  // Les chemins dans une ref AUSSI : l'élément naît après un chargement réseau, et
  // l'effet qui les pose s'exécute avant lui dès que la requête des chemins répond la
  // première. Il ne se rejouerait plus — `paths` ne change plus ensuite —, et la
  // complétion restait muette sans qu'aucune erreur ne le dise (Gael, 31/10/2026).
  const known = useRef(paths);
  known.current = paths;

  useEffect(() => {
    let alive = true;
    void loadComponent().then(() => {
      if (!alive || host.current === null || editor.current !== null) {
        return;
      }
      const element = document.createElement("jslt-editor") as EditorElement;
      element.setAttribute("catalog-url", CATALOG);
      element.setAttribute("aria-label", ariaLabel);
      element.value = value;
      element.addEventListener("input", () => changed.current(element.value));
      element.addEventListener("keydown", (event) => {
        if (runsOn(event as KeyboardEvent)) {
          // Sans cela, F5 recharge la page et perd le template en cours.
          event.preventDefault();
          run.current?.();
        }
      });
      host.current.append(element);
      editor.current = element;
      // Posés ICI aussi : si les chemins étaient déjà là, l'effet qui les pose est
      // passé pour rien avant que l'élément n'existe.
      applyPaths(element, known.current);
    });
    return () => {
      alive = false;
    };
    // Monté une fois : la valeur suit par l'effet ci-dessous.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // Réécrit seulement si la valeur vient d'ailleurs (bouton « remplir ») : réaffecter
    // à chaque frappe replacerait le curseur en fin de texte.
    if (editor.current !== null && editor.current.value !== value) {
      editor.current.value = value;
    }
  }, [value]);

  useEffect(() => {
    editor.current?.toggleAttribute("readonly", readOnly);
  }, [readOnly]);

  useEffect(() => {
    if (editor.current !== null) {
      applyPaths(editor.current, paths);
    }
  }, [paths]);

  return <div className="jslt-editor-host" ref={host} />;
}
