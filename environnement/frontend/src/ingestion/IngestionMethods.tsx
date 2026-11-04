import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@miles/socle-web";

import { FileTrialForm } from "./FileTrialForm";
import {
  type Method,
  type Trial,
  useIngestionMethods,
  useReissueSelfKey,
  useTryMethod,
} from "../api/ingestion";

/**
 * L'essai des méthodes d'UNE source : une adresse, un corps, un dépôt.
 *
 * **Ce bloc ne DÉCRIT plus rien** depuis que l'onglet voisin montre le contrat dans un
 * visualiseur Swagger (Gael, 04/11/2026) : en-têtes, corps attendu, réponses et schémas
 * y sont, et les redire ici aurait fait deux présentations de la même chose — celle
 * qu'on régénère et celle qu'on oublie.
 *
 * **L'essai dépose pour de vrai.** Aucun garde-fou, décidé le 04/11/2026 : il transforme,
 * écrit, fait avancer la date de dernière vue et produit ses events, comme n'importe quel
 * appel de partenaire. La trace est le journal, dans le troisième onglet.
 *
 * **Aucune clé à fournir.** Le back-office détient la sienne et frappe sa propre route :
 * la valeur ne descend jamais jusqu'ici. C'est aussi pourquoi le « Try it out » de
 * Swagger reste éteint — il partirait sans clé.
 */
export function IngestionMethods({ source }: { source: string }) {
  const { t } = useTranslation();
  const methods = useIngestionMethods();
  // Filtrées ICI et non demandées filtrées au serveur : la route rend les méthodes de la
  // version servie, et une source est précisément une tranche de cette réponse. Un
  // paramètre de plus aurait fait une seconde requête par source, pour une liste que la
  // page voisine a déjà en cache.
  const propres = (methods.data?.methods ?? []).filter((method) => method.source === source);

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
  if (propres.length === 0) {
    // L'état normal d'une source dont la version servie ne déclare aucune entrée. Ce
    // n'est pas une panne, et l'écran ne doit pas le présenter comme telle.
    return <p className="help">{t("ingestion.methods.none")}</p>;
  }
  return (
    <section aria-labelledby="ingestion-methods-title">
      <div className="card-head">
        <h2 id="ingestion-methods-title">{t("ingestion.methods.title")}</h2>
      </div>
      <ul className="plain-list">
        {propres.map((method) => (
          <MethodCard key={`${method.source}:${method.mode}`} method={method} />
        ))}
      </ul>
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
  const trial = useTryMethod();

  return (
    <li className="card">
      <div className="card-head">
        {/* Le mode n'est pas répété à côté du chemin : il EST le dernier segment de
            l'adresse (« le mode est l'adresse », Gael, 02/11/2026). Le redire affichait
            « /ingest/<source>/element element », sous une classe que la feuille du socle
            ne porte même pas — vu dans un vrai navigateur, invisible sous jsdom. */}
        <h3 className="mono">POST {method.path}</h3>
      </div>
      <p className="caption">
        <span className="mono">{method.entry_model}</span>
        {" → "}
        <span className="mono">{method.storage}</span>
      </p>
      {method.model_refusal !== null && (
        // Nommé, et non remplacé par un corps vide : la vraie information est qu'une
        // pièce manque à la version servie, pas que la méthode n'attend rien. HORS du
        // repli, parce qu'une page qui cache ce qui manque ne sert à rien.
        <p className="alert" role="status">
          {t(`ingestion.methods.${method.model_refusal}`, { model: method.entry_model })}
        </p>
      )}
      {/* REPLIÉ par défaut (Gael, 04/11/2026 : « la présentation de la page est trop
          chargée »). La ligne au-dessus suffit à parcourir les méthodes ; on n'ouvre que
          celle qu'on dépose. */}
      <details>
        <summary>{t("ingestion.methods.open")}</summary>
        <MethodTrial method={method} trial={trial} />
      </details>
      {trial.isError && <TrialFailure error={trial.error} />}
      {trial.data !== undefined && <TrialResponse trial={trial.data} />}
    </li>
  );
}

/**
 * L'essai d'une méthode : un corps à saisir, ou un fichier à choisir.
 *
 * **Pas de geste sans schéma** : le point d'entrée refuserait le dépôt entier pour la même
 * raison — la version servie ne porte pas ce qu'il lui faut —, et un bouton promettrait un
 * essai qu'aucune saisie ne peut faire aboutir.
 */
function MethodTrial({
  method,
  trial,
}: {
  method: Method;
  trial: ReturnType<typeof useTryMethod>;
}) {
  const { t } = useTranslation();
  // Le corps part du gabarit du modèle, puis appartient à qui le modifie : le resemer
  // depuis les props écraserait une saisie en cours.
  const [body, setBody] = useState(() =>
    method.example === null ? "" : `${JSON.stringify(method.example, null, 2)}\n`,
  );

  if (!method.served) {
    return <p className="muted">{t("ingestion.methods.notServed")}</p>;
  }
  if (method.model_refusal !== null) {
    return null;
  }
  // Le mode fichier dépose un DOCUMENT choisi sur le disque, et non un corps saisi : son
  // découpage désigne un tableau dedans, et un document d'import ne se tape pas.
  if (method.mode === "fichier") {
    return (
      <FileTrialForm
        method={method}
        pending={trial.isPending}
        onDeposit={(choisi) =>
          trial.mutate({ source: method.source, mode: method.mode, body: choisi })
        }
      />
    );
  }
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        trial.mutate({ source: method.source, mode: method.mode, body });
      }}
      aria-label={t("ingestion.methods.form", { path: method.path })}
    >
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
