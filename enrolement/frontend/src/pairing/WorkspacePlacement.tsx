import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useExposedWorkspaces } from "../api/confiedGit";
import { exposedInRefusal, useEnvironments, usePlaceWorkspace } from "../api/environments";
import type { PairedEnvironment } from "../api/pairing";

/**
 * Le workspace que cet environnement hébergera (Gael, 01/11/2026).
 *
 * Le choix est posé sur l'ENVIRONNEMENT, pas sur l'appariement, et c'est ce qui le fait
 * survivre à une révocation suivie d'un réappariement. Il s'offre ici parce que c'est
 * l'écran où l'on voit les deux à la fois — la stack et l'environnement qu'elle sert.
 *
 * Rien à offrir tant qu'aucun environnement n'est rattaché : il n'y a pas de sujet sur
 * quoi poser le workspace, et une liste déroulante active sans destination ferait croire
 * à un geste qui ne peut pas aboutir.
 */
export function WorkspacePlacement({ environnement }: { environnement: PairedEnvironment }) {
  const { t } = useTranslation();
  const cible = environnement.environment;
  const expose = useExposedWorkspaces();
  const place = usePlaceWorkspace();
  // Le workspace placé est lu du RÉFÉRENTIEL et non de l'appariement : c'est
  // l'environnement qui l'héberge, et c'est cette liste que l'écriture rafraîchit.
  const referentiel = useEnvironments();
  // `undefined` = rien touché ; une chaîne vide = « aucun », choisi exprès.
  const [choisi, setChoisi] = useState<string | undefined>(undefined);

  if (cible === null) {
    return null;
  }
  const courant = referentiel.data?.find((e) => e.id === cible.id)?.workspace_id ?? "";
  const valeur = choisi ?? courant;
  const refuses = exposedInRefusal(place.error);
  // Le workspace déjà placé reste proposé même s'il n'est plus exposé : sinon la liste
  // s'ouvrirait sur « aucun » et un enregistrement distrait le retirerait sans le dire.
  const connus = expose.workspaces.map((workspace) => workspace.id);
  const options = courant !== "" && !connus.includes(courant) ? [courant, ...connus] : connus;

  return (
    <div className="cell">
      <label className="field">
        {t("pairing.workspacePlacement.caption")}
        <select
          value={valeur}
          disabled={place.isPending}
          onChange={(event) => setChoisi(event.target.value)}
        >
          <option value="">{t("pairing.workspacePlacement.none")}</option>
          {options.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
      </label>
      <div className="actions row-actions">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={place.isPending || valeur === courant}
          onClick={() =>
            place.mutate(
              { id: cible.id, workspaceId: valeur === "" ? null : valeur },
              { onSuccess: () => setChoisi(undefined) },
            )
          }
        >
          {t("pairing.workspacePlacement.submit")}
        </button>
      </div>
      {options.length === 0 && (
        // Aucun workspace exposé : le geste à faire est chez le module de paramétrage,
        // et le dire évite de chercher ici un écran de création qui n'existe pas.
        <p className="help" role="status">
          {t("pairing.workspacePlacement.noneExposed")}
        </p>
      )}
      {refuses !== null && (
        <p className="alert alert-danger" role="alert">
          {t("pairing.workspacePlacement.notExposed", {
            exposed: refuses.join(", ") || t("pairing.workspacePlacement.nothing"),
          })}
        </p>
      )}
      {place.isError && refuses === null && (
        <p className="alert alert-danger" role="alert">
          {t("pairing.workspacePlacement.error")}
        </p>
      )}
    </div>
  );
}
