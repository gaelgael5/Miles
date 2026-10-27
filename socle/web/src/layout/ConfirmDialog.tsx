import { type ReactNode, useEffect, useId, useRef } from "react";

/**
 * Fenêtre de confirmation d'une action irréversible.
 *
 * Écrite à la main plutôt qu'avec `<dialog>.showModal()`, que jsdom n'implémente pas :
 * les tests ne pourraient pas éprouver la garde. Le focus part sur « Annuler », et
 * Échap ou un clic à côté annulent : seule une validation explicite déclenche l'action.
 */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const cancel = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancel.current?.focus();
  }, []);

  return (
    <div className="overlay" onClick={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            onCancel();
          }
        }}
      >
        <h2 id={titleId}>{title}</h2>
        {children}
        <div className="actions dialog-actions">
          <button ref={cancel} type="button" className="btn btn-secondary" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button type="button" className="btn btn-danger" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
