import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@miles/socle-web";

import { FileTrialForm } from "./FileTrialForm";
import {
  type ContractResponse,
  type Method,
  type Trial,
  useIngestionContract,
  useIngestionMethods,
  useReissueSelfKey,
  useTryMethod,
} from "../api/ingestion";

/**
 * Les méthodes d'ingestion présentées comme un contrat, et essayables sur place
 * (Gael, 04/11/2026 : « réorganiser la page de service pour le voir comme une page
 * swagger qui permettrait de tester les méthodes »).
 *
 * **L'essai dépose pour de vrai.** Aucun garde-fou, décidé le 04/11/2026 : il transforme,
 * écrit, fait avancer la date de dernière vue et produit ses events, comme n'importe quel
 * appel de partenaire. La trace est le journal des appels, juste en dessous.
 *
 * **Aucune clé à fournir.** Le back-office détient la sienne et frappe sa propre route :
 * la valeur ne descend jamais jusqu'ici.
 */
export function IngestionMethods() {
  const { t } = useTranslation();
  const methods = useIngestionMethods();

  if (methods.isPending) {
    return (
      <p className="muted" role="status">
        {t("ingestion.methods.loading")}
      </p>
    );
  }
  if (methods.isError) {
    return (
      <p className="alert" role="alert">
        {t("ingestion.methods.unreadable")}
      </p>
    );
  }
  if (methods.data.methods.length === 0) {
    // L'état normal d'une stack sans version servie : aucune source déclarée, donc aucune
    // méthode. Ce n'est pas une panne, et l'écran ne doit pas le présenter comme telle.
    return <p className="help">{t("ingestion.methods.none")}</p>;
  }
  return (
    <section aria-labelledby="ingestion-methods-title">
      <div className="card-head">
        <h2 id="ingestion-methods-title">{t("ingestion.methods.title")}</h2>
      </div>
      <ul className="plain-list">
        {methods.data.methods.map((method) => (
          <MethodCard key={`${method.source}:${method.mode}`} method={method} />
        ))}
      </ul>
      <ContractResponses />
    </section>
  );
}

/** Le code de refus que porte une réponse d'erreur de la route d'écran, ou null. */
function refusalOf(error: unknown): string | null {
  if (!(error instanceof ApiError)) {
    return null;
  }
  const detail = error.detail as { code?: unknown } | undefined;
  return typeof detail?.code === "string" ? detail.code : null;
}

function MethodCard({ method }: { method: Method }) {
  const { t } = useTranslation();
  // Le corps part du gabarit du modèle, puis appartient à qui le modifie : le resemer
  // depuis les props écraserait une saisie en cours.
  const [body, setBody] = useState(() =>
    method.example === null ? "" : `${JSON.stringify(method.example, null, 2)}\n`,
  );
  const trial = useTryMethod();
  // Le mode fichier dépose un DOCUMENT choisi sur le disque, et non un corps saisi : son
  // découpage désigne un tableau dedans, et un document d'import ne se tape pas.
  const fichier = method.mode === "fichier";

  function submit(event: FormEvent) {
    event.preventDefault();
    trial.mutate({ source: method.source, mode: method.mode, body });
  }

  return (
    <li className="card">
      <div className="card-head">
        <h3 className="mono">
          POST {method.path} <span className="chip">{method.mode}</span>
        </h3>
      </div>
      <p className="caption">
        <span className="mono">{method.entry_model}</span>
        {" → "}
        <span className="mono">{method.storage}</span>
      </p>
      {method.model_refusal !== null && (
        // Nommé, et non remplacé par un corps vide : la vraie information est qu'une
        // pièce manque à la version servie, pas que la méthode n'attend rien.
        <p className="alert" role="status">
          {t(`ingestion.methods.${method.model_refusal}`, { model: method.entry_model })}
        </p>
      )}
      {/* Pas de formulaire sans schéma : le point d'entrée refuserait le dépôt entier
          pour la même raison — la version servie ne porte pas ce qu'il lui faut —, et un
          bouton promettrait un essai qu'aucune saisie ne peut faire aboutir. */}
      {!method.served || method.model_refusal !== null ? (
        !method.served && <p className="muted">{t("ingestion.methods.notServed")}</p>
      ) : fichier ? (
        <FileTrialForm
          method={method}
          pending={trial.isPending}
          onDeposit={(choisi) =>
            trial.mutate({ source: method.source, mode: method.mode, body: choisi })
          }
        />
      ) : (
        <form onSubmit={submit} aria-label={t("ingestion.methods.form", { path: method.path })}>
          <label className="field">
            {t("ingestion.methods.body")}
            <textarea
              rows={8}
              className="mono"
              value={body}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          <div className="actions">
            <button type="submit" className="btn btn-primary" disabled={trial.isPending}>
              {trial.isPending ? t("ingestion.methods.depositing") : t("ingestion.methods.deposit")}
            </button>
          </div>
        </form>
      )}
      {trial.isError && <TrialFailure error={trial.error} />}
      {trial.data !== undefined && <TrialResponse trial={trial.data} />}
    </li>
  );
}

/**
 * Ce que le point d'entrée a répondu. Le statut est celui du DÉPÔT : un lot entièrement
 * rejeté rend 422, et le montrer comme un refus du dépôt — et non comme une panne de
 * l'écran — est tout l'intérêt de l'essai.
 */
function TrialResponse({ trial }: { trial: Trial }) {
  const { t } = useTranslation();
  const accepte = trial.status >= 200 && trial.status < 300;

  return (
    <section className="card-inset" aria-label={t("ingestion.methods.response")}>
      <p className={accepte ? "caption" : "alert"} role="status">
        {t("ingestion.methods.responseStatus", { status: trial.status })}
      </p>
      <pre className="mono">{JSON.stringify(trial.body, null, 2)}</pre>
    </section>
  );
}

/**
 * Un essai qui n'a pas pu PARTIR, par opposition à un dépôt refusé.
 *
 * La clé révoquée se dit nommément : relayée en refus d'authentification nu, on en
 * chercherait la cause du côté du paramétrage ou des octrois.
 */
function TrialFailure({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const reissue = useReissueSelfKey();
  const code = refusalOf(error);

  if (code !== "cle_du_back_office_revoquee") {
    return (
      <p className="alert" role="alert">
        {t("ingestion.methods.failed", { code: code ?? "" })}
      </p>
    );
  }
  return (
    <div className="alert" role="alert">
      <p>{t("ingestion.methods.keyRevoked")}</p>
      <div className="actions">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={reissue.isPending || reissue.isSuccess}
          onClick={() => reissue.mutate()}
        >
          {reissue.isSuccess ? t("ingestion.methods.reissued") : t("ingestion.methods.reissue")}
        </button>
      </div>
    </div>
  );
}

/**
 * Les réponses que le contrat PUBLIÉ déclare, avec leurs statuts.
 *
 * Lues et non recopiées : un refus ajouté au contrat apparaît ici sans qu'on touche à
 * cette page. Affichées une fois pour la page — elles sont les mêmes pour toutes les
 * méthodes, et les répéter par bloc n'apprendrait rien.
 */
function ContractResponses() {
  const { t } = useTranslation();
  const contract = useIngestionContract();

  if (contract.isPending || contract.isError || contract.data.length === 0) {
    // Muet plutôt qu'alarmant : le contrat est un complément de lecture, et son absence
    // n'empêche ni de lire les méthodes ni d'en essayer une.
    return null;
  }
  return (
    <details className="card">
      <summary>{t("ingestion.methods.contract")}</summary>
      <ul className="plain-list">
        {contract.data.map((response: ContractResponse) => (
          <li key={response.status} className="row">
            <div className="row-main">
              <span className="row-title mono">{response.status}</span>
              <div className="row-sub">{response.description}</div>
            </div>
          </li>
        ))}
      </ul>
    </details>
  );
}
