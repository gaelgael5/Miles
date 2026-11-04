import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";

import {
  type EditorMetrics,
  FALLBACK,
  lineCount,
  metricsOf,
  offsetOfLine,
  textTopWithin,
  viewportOf,
} from "./editorMetrics";

const JsltEditor = lazy(() => import("./JsltEditor"));

/** Où poser la gouttière et la bande, une fois la zone de saisie mesurée. */
interface Placement {
  /** Hauteur à donner à la gouttière ; `null` : la laisser prendre celle de son contenu. */
  viewport: number | null;
  /** Haut du texte, depuis le haut du contenu de la gouttière. */
  inGutter: number;
  /** Haut du texte, depuis le haut du cadre. */
  inFrame: number;
}

const UNMEASURED: Placement = {
  viewport: null,
  inGutter: FALLBACK.paddingTop,
  inFrame: FALLBACK.paddingTop,
};

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
  const [placement, setPlacement] = useState<Placement>(UNMEASURED);
  const gutter = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);

  const measure = useCallback((area: HTMLTextAreaElement) => {
    const read = metricsOf(area);
    setMetrics(read);
    setPlacement({
      viewport: viewportOf(area),
      inGutter: gutter.current === null ? read.paddingTop : textTopWithin(area, gutter.current, read),
      inFrame: frame.current === null ? read.paddingTop : textTopWithin(area, frame.current, read),
    });
  }, []);

  useEffect(() => {
    if (area === null) {
      return;
    }
    measure(area);
    // La gouttière suit le défilement de la zone de saisie, qui défile seule : sans cet
    // abonnement, les numéros restent en place et désignent les mauvaises lignes dès
    // qu'un template dépasse la hauteur visible.
    const follow = () => setScrollTop(area.scrollTop);
    area.addEventListener("scroll", follow);
    follow();
    // La zone de saisie est redimensionnable à la verticale (`resize: vertical`, feuille
    // du composant) : sans observateur, la gouttière garderait la hauteur du premier
    // rendu et se décrocherait du cadre dès le premier étirement.
    const observer = new ResizeObserver(() => measure(area));
    observer.observe(area);
    return () => {
      area.removeEventListener("scroll", follow);
      observer.disconnect();
    };
  }, [area, measure]);

  const lines = lineCount(value);
  const marked = errorLine !== null && errorLine !== undefined && errorLine >= 1;

  return (
    <div className="template-editor">
      {/* `aria-hidden` : les numéros sont un repère visuel. Annoncés, un lecteur
          d'écran lirait « un deux trois… » avant d'arriver au template. */}
      <div
        className="template-gutter"
        aria-hidden="true"
        ref={gutter}
        // Bornée à la hauteur visible de la zone de saisie, et pas à son contenu :
        // sinon c'est la gouttière qui donne sa hauteur à l'assemblage, et les numéros
        // continuent bien au-dessous du cadre de l'éditeur.
        style={placement.viewport === null ? undefined : { height: `${placement.viewport}px` }}
      >
        <div
          className="template-gutter-lines"
          style={{
            transform: `translateY(${-scrollTop}px)`,
            paddingTop: `${placement.inGutter}px`,
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
      <div className="template-frame" ref={frame}>
        {marked && (
          // Le surlignement est posé PAR-DESSUS, sans toucher au texte : teinter le
          // texte lui-même voudrait dire réécrire la coloration du composant.
          <div
            className="template-error-line"
            data-line={errorLine}
            style={{
              top: `${offsetOfLine(errorLine, scrollTop, placement.inFrame, metrics)}px`,
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
