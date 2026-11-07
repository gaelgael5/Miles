import { useTranslation } from "react-i18next";

import { CopyButton } from "@miles/socle-web";

import { type Method, useIngestionMethods } from "../api/ingestion";

const KEY_PLACEHOLDER = "VOTRE_CLE_API";
const FILE_PLACEHOLDER = "document.json";

/**
 * La commande `curl` qui appelle chaque méthode de la source (Gael, 07/11/2026).
 *
 * **Construite ici et non prise à Swagger UI, et ce n'est pas un choix de confort.**
 * L'extrait `curl` natif de Swagger est rendu par son composant `LiveResponse`, donc
 * seulement APRÈS l'exécution d'un « Try it out » — vérifié dans le bundle installé. Or
 * le « Try it out » est éteint délibérément : la clé d'API ne descend jamais jusqu'au
 * navigateur, un essai partirait sans clé et rendrait 401, qu'on lirait comme un refus du
 * point d'entrée. Activer l'un pour obtenir l'autre aurait donc rouvert cette décision
 * pour une commodité.
 *
 * Bâtie sur la liste des MÉTHODES et non sur le document OpenAPI : le mode y est une
 * donnée (`mode`), là où il faudrait le deviner du dernier segment d'un chemin dans le
 * document. Une forme devinée casse en silence le jour où le gabarit d'adresse change.
 *
 * La clé est un ESPACE RÉSERVÉ, jamais une vraie : la clé d'un environnement n'existe pas
 * dans le navigateur, et une commande qui en contiendrait une finirait dans un historique
 * de terminal.
 */
export function ContractCurl({ source }: { source: string }) {
  const { t } = useTranslation();
  const methods = useIngestionMethods();
  const propres = (methods.data?.methods ?? []).filter(
    (method) => method.source === source && method.served,
  );

  if (propres.length === 0) {
    // Ni attente ni erreur affichées : le bloc voisin du contrat les porte déjà pour la
    // même requête, et deux messages pour une seule panne en font deux pannes.
    return null;
  }
  return (
    <section className="panel contract-curl" aria-label={t("ingestion.curl.title")}>
      <p className="caption">{t("ingestion.curl.title")}</p>
      {propres.map((method) => (
        <div className="curl-method" key={method.path}>
          <p className="curl-mode">{t(`ingestion.modes.${method.mode}`)}</p>
          <pre className="mono curl-command">{curlFor(method)}</pre>
          <CopyButton text={curlFor(method)} label={t("ingestion.curl.copy")} />
        </div>
      ))}
      <p className="help">{t("ingestion.curl.help", { placeholder: KEY_PLACEHOLDER })}</p>
    </section>
  );
}

/**
 * La commande d'une méthode, prête à coller.
 *
 * Le corps diffère selon le mode, et c'est la seule différence : le mode `fichier` envoie
 * un DOCUMENT depuis le disque (`--data-binary @`), qui peut peser des centaines de
 * mégaoctets et n'a donc rien à faire sur une ligne de commande ; les deux autres portent
 * le gabarit que le contrat publie, celui-là même que l'onglet d'essai sème dans sa zone
 * de saisie.
 */
export function curlFor(method: Method): string {
  const url = new URL(method.path, window.location.origin).toString();
  const lignes = [
    `curl -X POST ${quote(url)}`,
    `  -H ${quote(`X-API-Key: ${KEY_PLACEHOLDER}`)}`,
    `  -H ${quote("Content-Type: application/json")}`,
    method.mode === "fichier"
      ? `  --data-binary ${quote(`@${FILE_PLACEHOLDER}`)}`
      : `  --data ${quote(body(method))}`,
  ];
  return lignes.join(" \\\n");
}

/**
 * Le texte entre apostrophes simples, utilisable tel quel par un shell POSIX.
 *
 * **L'apostrophe doit être traitée, et ce n'est pas théorique** : un gabarit de point
 * relais porte « Épicerie d'Or » dès qu'un libellé en contient une. Sans ce traitement,
 * la commande collée se referme au milieu du corps et le shell attend une suite qui ne
 * vient pas — ou pire, exécute ce qui suit. Une apostrophe se rend en fermant la chaîne,
 * en l'échappant, et en la rouvrant.
 */
function quote(valeur: string): string {
  return `'${valeur.split("'").join(`'\\''`)}'`;
}

function body(method: Method): string {
  if (method.example === null || method.example === undefined) {
    return "{}";
  }
  // Compact : un gabarit indenté ferait une commande de trente lignes, et les retours à
  // la ligne d'un JSON collé dans un terminal cassent la continuation du shell.
  return JSON.stringify(method.example);
}
