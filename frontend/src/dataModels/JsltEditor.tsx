import { useEffect, useRef } from "react";

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

type EditorElement = HTMLElement & { value: string };

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
 */
export default function JsltEditor({
  value,
  onChange,
  onRun,
  readOnly,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  /** F5 : exécuter le template sans quitter le clavier. */
  onRun?: () => void;
  readOnly: boolean;
  ariaLabel: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<EditorElement | null>(null);
  // Tenu dans une ref : l'écouteur du composant vit plus longtemps qu'un rendu, et
  // capturerait sinon la première version de la fonction.
  const changed = useRef(onChange);
  changed.current = onChange;
  const run = useRef(onRun);
  run.current = onRun;

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
        if ((event as KeyboardEvent).key === "F5") {
          // Sans cela, F5 recharge la page et perd le template en cours.
          event.preventDefault();
          run.current?.();
        }
      });
      host.current.append(element);
      editor.current = element;
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

  return <div className="jslt-editor-host" ref={host} />;
}
