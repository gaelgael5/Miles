import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Method, Trial } from "../api/ingestion";

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
 */
export function FileTrialForm({
  method,
  pending,
  onDeposit,
}: {
  method: Method;
  pending: boolean;
  onDeposit: (file: File) => void;
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);

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
      <div className="actions">
        {/* Désactivé sans fichier : le point d'entrée refuserait un corps vide, et le
            refus parlerait du document au lieu de parler du geste manquant. */}
        <button type="submit" className="btn btn-primary" disabled={pending || file === null}>
          {pending ? t("ingestion.methods.depositing") : t("ingestion.methods.deposit")}
        </button>
      </div>
    </form>
  );
}

/** Vrai quand la réponse est un acquittement de PRISE EN CHARGE, et non un compte-rendu. */
export function isAccepted(trial: Trial): boolean {
  return trial.status === 202;
}
