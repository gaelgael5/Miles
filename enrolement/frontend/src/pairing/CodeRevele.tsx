import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { CopyButton } from "@miles/socle-web";

import { usePairingCode } from "../api/pairing";

/** Secondes restantes avant un instant donné, jamais négatives. */
export function resteJusqua(instant: string, maintenant: number): number {
  return Math.max(0, Math.round((Date.parse(instant) - maintenant) / 1000));
}

/**
 * Une horloge qui bat à la seconde, pour les comptes à rebours affichés.
 *
 * Locale et uniquement pour l'AFFICHAGE : ce qui décide de l'acceptation d'un code est
 * l'horloge du serveur, et les deux n'ont aucune raison de s'accorder. Afficher un compte
 * à rebours dérivé du serveur à chaque seconde coûterait une requête par seconde.
 */
export function useTicTac(): number {
  const [maintenant, setMaintenant] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setMaintenant(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return maintenant;
}

export function Duree({ secondes }: { secondes: number }) {
  const { t } = useTranslation();
  const minutes = Math.floor(secondes / 60);
  // Trois échelles, parce que la durée de vie d'une demande est PARAMÉTRABLE : une heure
  // par défaut, sept jours au plus. « dans 10080 min » est exact et illisible.
  const libelle =
    minutes >= 60
      ? t("pairing.requests.expiresInHours", { n: Math.round(minutes / 60) })
      : minutes >= 1
        ? t("pairing.requests.expiresInMinutes", { n: minutes })
        : t("pairing.requests.expiresInSeconds", { n: secondes });
  return <span className={secondes === 0 ? "badge badge-warning" : "badge"}>{libelle}</span>;
}

/**
 * Le code à recopier, et ce qu'il reste de sa fenêtre.
 *
 * Il n'est ni imprimable, ni téléchargeable, ni exportable : la seule sortie offerte est
 * le presse-papiers. Le rendre exportable en ferait un secret qui traîne, alors qu'il est
 * conçu pour ne valoir que quelques secondes et qu'une fois.
 */
export function CodeRevele({ baseUrl }: { baseUrl: string }) {
  const { t } = useTranslation();
  const code = usePairingCode(baseUrl);
  const maintenant = useTicTac();
  const [lu, setLu] = useState(() => Date.now());

  useEffect(() => {
    if (code.data !== undefined) {
      setLu(Date.now());
    }
  }, [code.data]);

  if (code.isPending) {
    return <p role="status">{t("pairing.code.loading")}</p>;
  }
  if (code.data === undefined) {
    // Le plus souvent : la demande vient d'expirer ou d'être refusée ailleurs. Le dire
    // vaut mieux qu'afficher un code vide que quelqu'un recopierait.
    return (
      <p className="alert" role="status">
        {t("pairing.code.gone")}
      </p>
    );
  }
  // Borné par ce que le SERVEUR a dit : l'effet qui pose `lu` s'exécute après le rendu,
  // donc l'écart peut être très légèrement négatif et faire afficher une seconde de plus
  // que ce qu'il reste. Mieux vaut annoncer un peu moins qu'un peu trop.
  const reste = Math.min(
    code.data.seconds_remaining,
    Math.max(0, code.data.seconds_remaining - Math.floor((maintenant - lu) / 1000)),
  );
  return (
    <div className="row-detail">
      <p className="help">{t("pairing.code.handOver")}</p>
      {/* `actions` et non `facts` : `facts` est une grille à deux colonnes pour des
          couples légende/valeur, et le bouton de copie s'y étirait sur toute la largeur
          de la seconde colonne. Ici trois éléments se suivent sur une ligne. */}
      <div className="actions">
        <div className="code-block code-large" aria-label={t("pairing.code.label")}>
          {code.data.code}
        </div>
        <CopyButton text={code.data.code} label={t("pairing.code.copy")} />
        <span className={reste <= 5 ? "badge badge-warning" : "badge"} role="timer">
          {t("pairing.code.renewsIn", { n: reste })}
        </span>
      </div>
      <p className="help">{t("pairing.code.perishable")}</p>
    </div>
  );
}
