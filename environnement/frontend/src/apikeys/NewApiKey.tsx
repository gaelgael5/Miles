import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError } from "@miles/socle-web";

import { type IssuedKey, useIssueKey } from "../api/apikeys";

/**
 * Émettre une clé : un libellé, et les sources qu'elle ouvre.
 *
 * Les sources sont des cases à cocher et non une saisie : seules celles que la version
 * servie déclare peuvent être octroyées, et le serveur refuse les autres. Offrir un champ
 * libre ferait découvrir ce refus après coup.
 */
export function NewApiKey({ sources }: { sources: string[] }) {
  const { t } = useTranslation();
  const issue = useIssueKey();
  const [label, setLabel] = useState("");
  const [cochees, setCochees] = useState<string[]>([]);
  const [emise, setEmise] = useState<IssuedKey | null>(null);

  function bascule(source: string) {
    setCochees((avant) =>
      avant.includes(source) ? avant.filter((s) => s !== source) : [...avant, source],
    );
  }

  function emettre() {
    issue.mutate(
      { label, sources: cochees },
      {
        onSuccess: (resultat) => {
          setEmise(resultat);
          setLabel("");
          setCochees([]);
        },
      },
    );
  }

  if (emise !== null) {
    return <IssuedSecret emise={emise} onClose={() => setEmise(null)} />;
  }
  if (sources.length === 0) {
    // Rien à octroyer : une clé qui n'ouvre rien serait refusée, et le formulaire
    // promettrait un geste impossible. On dit pourquoi, plutôt que de l'afficher inerte.
    return <p className="help">{t("apiKeys.noSource")}</p>;
  }
  return (
    <form
      className="card"
      aria-label={t("apiKeys.new")}
      onSubmit={(event) => {
        event.preventDefault();
        emettre();
      }}
    >
      <div className="card-head">
        <h2>{t("apiKeys.new")}</h2>
      </div>
      <label className="field">
        {t("apiKeys.label")}
        <input value={label} onChange={(event) => setLabel(event.target.value)} />
      </label>
      <fieldset className="field">
        <legend>{t("apiKeys.sources")}</legend>
        {sources.map((source) => (
          <label key={source} className="check">
            <input
              type="checkbox"
              checked={cochees.includes(source)}
              onChange={() => bascule(source)}
            />
            <span className="mono">{source}</span>
          </label>
        ))}
      </fieldset>
      {issue.isError && <Refusal error={issue.error} />}
      <div className="actions">
        {/* Éteint sans libellé ni octroi : le serveur refuserait, et un refus qu'on peut
            empêcher de se produire vaut mieux qu'un refus qu'on explique. */}
        <button
          type="submit"
          className="btn btn-primary"
          disabled={label.trim() === "" || cochees.length === 0 || issue.isPending}
        >
          {t("apiKeys.issue")}
        </button>
      </div>
    </form>
  );
}

/**
 * La clé en clair, montrée cette seule fois.
 *
 * Elle n'est dans aucun état partagé et ne se relit par aucune route : fermer ce panneau
 * la perd définitivement, et l'écran le dit AVANT que la personne ne ferme.
 */
function IssuedSecret({ emise, onClose }: { emise: IssuedKey; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <section className="card" aria-label={t("apiKeys.issued")}>
      <div className="card-head">
        <h2>{t("apiKeys.issued")}</h2>
      </div>
      <p className="alert" role="status">
        {t("apiKeys.onlyOnce")}
      </p>
      <p className="mono selectable">{emise.secret}</p>
      <p className="caption">
        {emise.key.label} — {emise.key.sources.join(" · ")}
      </p>
      <div className="actions">
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          {t("apiKeys.close")}
        </button>
      </div>
    </section>
  );
}

/** Le refus du serveur, dit dans les mots de la personne plutôt qu'en code. */
function Refusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const detail =
    error instanceof ApiError && error.status === 422
      ? (error.detail as { reason?: string; source?: string } | undefined)
      : undefined;
  return (
    <p className="alert" role="alert">
      {detail?.reason === undefined
        ? t("apiKeys.errors.unknown")
        : t(`apiKeys.errors.${detail.reason}`, {
            defaultValue: t("apiKeys.errors.unknown"),
            source: detail.source ?? "",
          })}
    </p>
  );
}
