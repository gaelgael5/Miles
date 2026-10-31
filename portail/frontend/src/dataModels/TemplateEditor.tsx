import { Suspense, lazy, useEffect, useRef, useState } from "react";

import { type EditorMetrics, FALLBACK, lineCount, metricsOf, offsetOfLine } from "./editorMetrics";

const JsltEditor = lazy(() => import("./JsltEditor"));

/**
 * L'éditeur de template avec ce qui l'entoure : les numéros de ligne à gauche, et la
 * ligne fautive surlignée (Gael, 31/10/2026).
 *
 * Autour et non dedans : le Web Component vient d'`urban-json-editor`, que Miles sert
 * mais n'écrit pas. Lui ajouter une gouttière voudrait dire modifier son DOM interne,
 * qui changerait sous nos pieds à la première mise à jour. Ici, tout s'aligne sur sa
 * zone de saisie par ses propres mesures.
 *
 * C'est aussi ce qui rend la chose éprouvable : le composant est doublé dans les tests
 * par un `<textarea>`, et la gouttière, elle, est le code de Miles.
 */
export function TemplateEditor({
  value,
  onChange,
  onRun,
  onOpenSource,
  readOnly,
  ariaLabel,
  paths,
  errorLine,
  loading,
}: {
  value: string;
  onChange: (value: string) => void;
  onRun?: () => void;
  onOpenSource?: () => void;
  readOnly: boolean;
  ariaLabel: string;
  paths?: unknown[];
  /** La ligne que le serveur a refusée, à partir de 1. `null` : rien à signaler. */
  errorLine?: number | null;
  loading: string;
}) {
  const [area, setArea] = useState<HTMLTextAreaElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [metrics, setMetrics] = useState<EditorMetrics>(FALLBACK);
  const gutter = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (area === null) {
      return;
    }
    setMetrics(metricsOf(area));
    // La gouttière suit le défilement de la zone de saisie, qui défile seule : sans cet
    // abonnement, les numéros restent en place et désignent les mauvaises lignes dès
    // qu'un template dépasse la hauteur visible.
    const follow = () => setScrollTop(area.scrollTop);
    area.addEventListener("scroll", follow);
    follow();
    return () => area.removeEventListener("scroll", follow);
  }, [area]);

  const lines = lineCount(value);
  const marked = errorLine !== null && errorLine !== undefined && errorLine >= 1;

  return (
    <div className="template-editor">
      {/* `aria-hidden` : les numéros sont un repère visuel. Annoncés, un lecteur
          d'écran lirait « un deux trois… » avant d'arriver au template. */}
      <div className="template-gutter" aria-hidden="true" ref={gutter}>
        <div
          className="template-gutter-lines"
          style={{
            transform: `translateY(${-scrollTop}px)`,
            paddingTop: `${metrics.paddingTop}px`,
            lineHeight: `${metrics.lineHeight}px`,
            fontSize: `${metrics.fontSize}px`,
          }}
        >
          {Array.from({ length: lines }, (_, index) => (
            <div
              key={index}
              className={marked && index + 1 === errorLine ? "gutter-line gutter-error" : "gutter-line"}
            >
              {index + 1}
            </div>
          ))}
        </div>
      </div>
      <div className="template-frame">
        {marked && (
          // Le surlignement est posé PAR-DESSUS, sans toucher au texte : teinter le
          // texte lui-même voudrait dire réécrire la coloration du composant.
          <div
            className="template-error-line"
            data-line={errorLine}
            style={{
              top: `${offsetOfLine(errorLine, scrollTop, metrics)}px`,
              height: `${metrics.lineHeight}px`,
            }}
          />
        )}
        <Suspense fallback={<p className="muted">{loading}</p>}>
          <JsltEditor
            value={value}
            onChange={onChange}
            onRun={onRun}
            onOpenSource={onOpenSource}
            onReady={setArea}
            readOnly={readOnly}
            ariaLabel={ariaLabel}
            paths={paths}
          />
        </Suspense>
      </div>
    </div>
  );
}
