import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

type Outcome = "idle" | "copied" | "failed";
// Assez long pour être vu, assez court pour qu'un second clic reparte d'un bouton neuf.
const FEEDBACK_MS = 2000;

/**
 * Copie un texte et le dit (Gael, 22/10/2026 : « une petite animation pour comprendre que
 * le clic est fait »). L'échec se dit aussi : hors HTTPS, le navigateur n'offre pas le
 * presse-papiers, et un bouton qui ne fait rien en silence laisserait croire la clé copiée.
 */
export function CopyButton({ text, label, disabled }: { text: string; label: string; disabled?: boolean }) {
  const { t } = useTranslation();
  const [outcome, setOutcome] = useState<Outcome>("idle");

  useEffect(() => {
    if (outcome === "idle") {
      return undefined;
    }
    const timer = window.setTimeout(() => setOutcome("idle"), FEEDBACK_MS);
    return () => window.clearTimeout(timer);
  }, [outcome]);

  function copy() {
    if (!navigator.clipboard) {
      setOutcome("failed");
      return;
    }
    navigator.clipboard.writeText(text).then(
      () => setOutcome("copied"),
      () => setOutcome("failed"),
    );
  }

  return (
    <button
      type="button"
      className={`btn btn-secondary copy-button${outcome === "idle" ? "" : ` copy-${outcome}`}`}
      disabled={disabled}
      onClick={copy}
    >
      {outcome === "copied" ? t("copy.done") : outcome === "failed" ? t("copy.failed") : label}
      <span className="visually-hidden" role="status">
        {outcome === "copied" ? t("copy.done") : outcome === "failed" ? t("copy.failedHelp") : ""}
      </span>
    </button>
  );
}
