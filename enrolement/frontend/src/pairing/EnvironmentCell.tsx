import { useTranslation } from "react-i18next";

import type { EnvironmentRef } from "../api/pairing";

/**
 * L'environnement rattaché, ou le signal qu'il manque.
 *
 * « À rattacher » porte une pastille d'alerte, et c'est voulu : un appariement sans
 * environnement est un état transitoire HÉRITÉ, pas l'état normal du premier jour — à
 * l'inverse d'un environnement déclaré et pas encore apparié, que le référentiel montre
 * en gris. Les deux absences ne se lisent pas pareil.
 *
 * Dans son propre fichier parce que les deux listes de l'écran l'emploient : la laisser
 * chez l'une ferait dépendre l'autre d'un fichier dont ce n'est pas le sujet.
 */
export function EnvironmentCell({ environnement }: { environnement: EnvironmentRef | null }) {
  const { t } = useTranslation();
  if (environnement === null) {
    return <span className="badge badge-warning">{t("pairing.designation.missing")}</span>;
  }
  return (
    <>
      <div>{environnement.label}</div>
      {/* Le slug sous le libellé : c'est lui qui s'écrit dans une procédure, et le
          retrouver sans changer d'écran évite de le recopier de mémoire. */}
      <div className="row-sub">{environnement.slug}</div>
    </>
  );
}
