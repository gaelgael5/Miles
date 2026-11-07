import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Method, Trial } from "../api/ingestion";
import type { UploadProgress } from "../api/upload";

/**
 * L'essai de la méthode `fichier` : un CHOIX DE FICHIER, pas une zone de texte.
 *
 * Le bloc du mode fichier existait depuis le ticket `a78551e5`, avec sa mention « pas
 * encore servie » et sans bouton. Le mode étant servi (story `0f14adbd`), le laisser
 * inerte promettrait une méthode que l'écran ne sait pas appeler (critère 21).
 *
 * **Un fichier et non un corps saisi**, parce que ce qu'on dépose ici est un DOCUMENT :
 * le découpage déclaré par l'entrée de source désigne un tableau DEDANS, et c'est le
 * gabarit montré au-dessus qui dit où. Coller un document de cinquante mille items dans
 * une zone de texte n'est pas le geste de cette méthode.
 *
 * **Et la réponse n'est pas un compte-rendu** : le dépôt rend un acquittement de prise en
 * charge, l'import se déroule après, et son issue se lit dans le journal des appels juste
 * en dessous. L'écran le dit, pour qu'un 202 ne se lise pas comme un import vide.
 *
 * **La progression de l'envoi est montrée depuis le 07/11/2026** (story `1a3fc5a7`). Gael
 * avait tenté deux fois de déposer un document de 943 Mo : « je n'en vois pas la fin. soit
 * parce que c est tres long soit parce que ca plante ». Sans progression, un envoi lent et
 * un envoi mort sont indiscernables, et c'est le seul formulaire du produit où l'attente
 * se compte en minutes.
 *
 * Ce qu'elle montre est l'ENVOI, pas l'import : elle se termine quand le document est sur
 * le disque de la stack et que le point d'entrée a rendu son identifiant de dépôt. L'import
 * commence après, et dure plus longtemps encore — c'est ce que dit la ligne d'aide, qui
 * renvoie au journal des appels.
 */
export function FileTrialForm({
  method,
  pending,
  progress,
  onDeposit,
  onCancel,
}: {
  method: Method;
  pending: boolean;
  progress: UploadProgress | null;
  onDeposit: (file: File) => void;
  onCancel: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const megaoctets = new Intl.NumberFormat(i18n.language, {
    style: "unit",
    unit: "megabyte",
    maximumFractionDigits: 1,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (file !== null) {
      onDeposit(file);
    }
  }

  return (
    <form onSubmit={submit} aria-label={t("ingestion.methods.form", { path: method.path })}>
      {method.example !== null && (
        <details>
          <summary>{t("ingestion.methods.fileExample")}</summary>
          <pre className="mono">{JSON.stringify(method.example, null, 2)}</pre>
        </details>
      )}
      <label className="field">
        {t("ingestion.methods.file")}
        {/* Ce que le contrat ne dit pas, et que l'écran seul peut dire : où lire la
            suite. Le reste — document posé sur disque, import hors de l'appel — est déjà
            dans la description de l'opération, juste au-dessus. */}
        {/* Un bloc et non un `span` : la feuille du socle style `.field > .help` comme
            une ligne à part, et en ligne il se collait au libellé — « Document à
            déposerL'issue de l'import… ». Vu dans un vrai navigateur. */}
        <div className="help">{t("ingestion.methods.fileHelp")}</div>
        <input
          type="file"
          accept="application/json,.json"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </label>
      {progress !== null && (
        <div className="upload-progress">
          {/* Un `progress` natif, et non une barre maison : il porte son rôle et ses
              valeurs aux technologies d'assistance sans qu'on ait à les déclarer. */}
          <progress
            value={progress.sent}
            max={progress.total}
            aria-label={t("ingestion.methods.uploadLabel")}
          />
          {/* Le pourcentage EN TEXTE, et pas seulement la barre : une barre seule ne se lit
              ni à la voix ni sur une capture d'écran envoyée pour demander de l'aide.
              `role="status"` le fait annoncer sans voler le focus. */}
          <p className="help" role="status">
            {t("ingestion.methods.uploading", {
              percent: percentOf(progress),
              sent: megaoctets.format(progress.sent / 1e6),
              total: megaoctets.format(progress.total / 1e6),
            })}
          </p>
        </div>
      )}
      <div className="actions">
        {/* Désactivé sans fichier : le point d'entrée refuserait un corps vide, et le
            refus parlerait du document au lieu de parler du geste manquant. */}
        <button type="submit" className="btn btn-primary" disabled={pending || file === null}>
          {pending ? t("ingestion.methods.depositing") : t("ingestion.methods.deposit")}
        </button>
        {/* Offert pendant l'envoi seulement : un document de plusieurs centaines de
            mégaoctets s'envoie en minutes, et sans ce geste la seule façon d'arrêter
            serait de quitter l'écran — en laissant le point d'entrée écrire sur le
            disque de la stack ce qu'on ne veut plus. */}
        {progress !== null && (
          <button type="button" className="btn" onClick={onCancel}>
            {t("ingestion.methods.uploadCancel")}
          </button>
        )}
      </div>
    </form>
  );
}

/**
 * Les pour cent d'un envoi, en entier.
 *
 * Un document VIDE vaut 100 % plutôt que `NaN` : zéro octet sur zéro n'est pas une
 * division qu'on fait, et l'écran doit montrer un envoi fini pour que le refus du point
 * d'entrée — `corps_vide` — soit ce que l'utilisateur lise ensuite.
 */
function percentOf(progress: UploadProgress): number {
  return progress.total === 0 ? 100 : Math.round((progress.sent / progress.total) * 100);
}

/** Vrai quand la réponse est un acquittement de PRISE EN CHARGE, et non un compte-rendu. */
export function isAccepted(trial: Trial): boolean {
  return trial.status === 202;
}
