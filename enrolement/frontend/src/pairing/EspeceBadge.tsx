import { useTranslation } from "react-i18next";

import type { PeerSpecies } from "../api/pairing";

/**
 * L'espèce du demandeur, et ce qu'accepter cette espèce-là entraîne.
 *
 * Le libellé seul ne suffit pas : « module de paramétrage » ne dit pas à un humain qu'il
 * s'apprête à lui confier des connexions git. La conséquence est donc écrite à côté,
 * parce que c'est sur elle que la décision se prend (critère 2 du ticket ba44914b).
 *
 * Un composant à lui parce qu'il paraît DEUX fois, sur deux écrans qui ne se ressemblent
 * pas — la liste des demandes en attente et la liste des appariés. Deux rendus du même
 * fait finiraient par ne plus dire la même chose, et le lecteur ne saurait lequel croire.
 */
export function EspeceBadge({ species }: { species: PeerSpecies }) {
  const { t } = useTranslation();
  // Classe distincte pour le paramétrage : il n'y en a qu'un, et ce qu'on lui confie
  // n'est pas de même nature. Un badge identique ferait chercher la différence dans le
  // texte, là où la liste en comptera des dizaines d'environnements.
  const classe = species === "parametrage" ? "badge badge-accent" : "badge";
  return (
    <>
      <span className={classe}>{t(`pairing.species.${species}`)}</span>
      <div className="row-sub">{t(`pairing.species.${species}Consequence`)}</div>
    </>
  );
}
