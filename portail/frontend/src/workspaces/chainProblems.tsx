import { useTranslation } from "react-i18next";

import { ApiError } from "@miles/socle-web";
import type { StepProblem } from "../api/chains";

/**
 * Les problèmes que porte un refus d'enregistrement de chaîne.
 *
 * Le serveur refuse en 422 avec `{code: "chaine_invalide", problems: [...]}`, et chaque
 * problème dit sa ligne, sa colonne et ce qui a été lu. Un écran qui se contente du code
 * HTTP affiche « voir les journaux du back-office » alors que la réponse qu'il tient dans
 * la main nomme exactement le caractère fautif (Gael, 31/10/2026). Partagé entre l'écran
 * de la chaîne et celui d'une étape : le défaut venait d'une seule des deux copies.
 */
export function savedProblems(error: unknown): StepProblem[] {
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail !== null) {
    const detail = error.detail as { code?: string; problems?: StepProblem[] };
    if (detail.code === "chaine_invalide") {
      return detail.problems ?? [];
    }
  }
  return [];
}

/**
 * Un problème rendu ENTIER, ses violations comprises.
 *
 * `hors_profil` est un libellé qui finit par deux-points et annonce une liste : sans les
 * violations, l'écran affichait « Constructions hors du profil d'écriture : » suivi de
 * rien. Le refus nommait pourtant chaque construction, sa ligne et sa colonne.
 */
export function StepProblems({ problems }: { problems: StepProblem[] }) {
  const { t } = useTranslation();
  return (
    <>
      {problems.map((problem) => (
        <div
          key={`${problem.step}-${problem.code}-${problem.detail ?? ""}`}
          className="alert row-detail"
          role="alert"
        >
          <p>
            {t(`chains.problems.${problem.code}`, {
              detail: problem.detail ?? "",
              line: problem.line,
              column: problem.column,
            })}
          </p>
          {problem.violations.length > 0 && (
            <ul className="plain-list">
              {problem.violations.map((violation) => (
                <li key={`${violation.construction}-${violation.line}-${violation.column}`}>
                  {t("chains.problems.violation", {
                    construction: violation.construction,
                    detail: violation.detail ?? "",
                    line: violation.line,
                    column: violation.column,
                  })}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </>
  );
}
