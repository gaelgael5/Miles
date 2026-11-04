import { useTranslation } from "react-i18next";

/**
 * Les trois gestes de l'appariement, et celui où l'on en est.
 *
 * Repris de la maquette « Appariement — côté demandeur » (28/10/2026), qui le place juste
 * sous le chapeau. Sa raison est écrite dans l'article des maquettes : les quatre états
 * que la page doit distinguer sont *non apparié*, *demande envoyée en attente*, *apparié*
 * et *refusée ou expirée*, et « un écran qui ne distingue pas en attente d'échoué fait
 * relancer la demande indéfiniment ». La pastille d'état dit ce qui EST ; le fil dit ce
 * qu'il reste à faire, ce qu'aucune pastille ne peut porter seule.
 *
 * **Une divergence assumée avec la maquette** : elle marque la deuxième étape comme FAITE
 * pendant que la demande attend. À cet instant précis elle ne l'est pas — c'est justement
 * ce qu'on attend —, et un écran qui coche l'acceptation avant qu'elle n'arrive ferait
 * chercher la panne ailleurs. L'étape attendue est donc rendue COURANTE, pas faite.
 *
 * Le fil disparaît une fois apparié : trois étapes grisées sous un état « Apparié »
 * n'apprennent plus rien, et la maquette ne les montre que tant qu'il reste à faire.
 */
export function FilDesEtapes({ courante }: { courante: 1 | 2 }) {
  const { t } = useTranslation();

  return (
    <ol className="steps">
      {([1, 2, 3] as const).map((rang) => (
        <li
          key={rang}
          className={rang === courante ? "step-now" : undefined}
          // `aria-current` et non la seule couleur : l'étape courante doit s'entendre.
          aria-current={rang === courante ? "step" : undefined}
        >
          {/* Le numéro est décoratif : c'est la liste ordonnée qui porte le rang, et le
              lire deux fois alourdit la restitution vocale sans rien ajouter. */}
          <span className="step-mark" aria-hidden="true">
            {rang}
          </span>
          {t(`peering.steps.${rang}`)}
        </li>
      ))}
    </ol>
  );
}
