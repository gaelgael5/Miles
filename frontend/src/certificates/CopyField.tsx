import { useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

type CopyState = "idle" | "copied" | "manual";

/**
 * Copie dans le presse-papiers. L'API Clipboard n'existe qu'en contexte sécurisé, or les
 * machines de test servent le portail en HTTP simple : repli volontaire sur l'ancienne
 * commande `copy` du texte sélectionné, et si elle aussi échoue, le texte reste
 * sélectionné pour un Ctrl+C manuel.
 */
async function copyText(area: HTMLTextAreaElement): Promise<boolean> {
  if (window.isSecureContext && typeof navigator.clipboard?.writeText === "function") {
    try {
      await navigator.clipboard.writeText(area.value);
      return true;
    } catch {
      // Permission refusée : on tente la sélection ci-dessous.
    }
  }
  area.focus();
  area.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  }
}

/** Texte public en lecture seule, avec son bouton Copier. */
export function CopyField({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation();
  const id = useId();
  const area = useRef<HTMLTextAreaElement>(null);
  const [state, setState] = useState<CopyState>("idle");

  async function copy() {
    if (area.current) {
      setState((await copyText(area.current)) ? "copied" : "manual");
    }
  }

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea
        id={id}
        ref={area}
        className="mono"
        readOnly
        rows={Math.min(value.trim().split("\n").length, 12)}
        value={value}
        onFocus={(e) => e.target.select()}
      />
      <div className="field-row">
        <button type="button" className="btn btn-secondary" onClick={() => void copy()}>
          {t("certificates.publicKey.copy")}
        </button>
        {state === "copied" && (
          <span className="badge badge-accent" role="status">
            {t("certificates.publicKey.copied")}
          </span>
        )}
        {state === "manual" && (
          <span className="help" role="status">
            {t("certificates.publicKey.copyManually")}
          </span>
        )}
      </div>
    </div>
  );
}

/** Clé publique et certificat d'un certificat client : les deux parties publiques. */
export function PublicParts({
  publicKey,
  certificate,
}: {
  publicKey: string | null;
  certificate: string;
}) {
  const { t } = useTranslation();
  return (
    <div>
      {publicKey === null ? (
        <p className="alert">{t("certificates.publicKey.unreadable")}</p>
      ) : (
        <CopyField label={t("certificates.publicKey.publicKey")} value={publicKey} />
      )}
      <CopyField label={t("certificates.publicKey.certificate")} value={certificate} />
      <p className="help">{t("certificates.publicKey.help")}</p>
    </div>
  );
}
