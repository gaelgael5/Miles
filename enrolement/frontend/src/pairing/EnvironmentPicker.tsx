import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { type Environment, useCreateEnvironment, useEnvironments } from "../api/environments";
import { designationRefusKey } from "../api/pairing";
import { EnvironmentForm } from "../environments/EnvironmentForm";

/**
 * Le choix de l'environnement auquel un appariement se rattache, et son raccourci de création.
 *
 * Le raccourci existe parce que c'est le cas NORMAL : on déploie une stack, elle frappe,
 * et l'environnement n'a pas encore été déclaré. Obliger à changer d'écran pour revenir
 * ensuite ferait perdre la demande de vue — et une demande a une échéance.
 *
 * Il obéit aux mêmes règles que le référentiel parce qu'il emploie le même formulaire :
 * libellé, slug dérivé puis libre, unicité tenue par le serveur. Réécrire ici un
 * formulaire « simplifié » ferait diverger les deux au premier changement de règle.
 */
export function EnvironmentPicker({
  choisi,
  pending,
  error,
  submitLabel,
  onChoose,
}: {
  /** L'environnement déjà désigné, pour le présélectionner. Nul quand rien ne l'est. */
  choisi: string | null;
  pending: boolean;
  error: unknown;
  submitLabel: string;
  onChoose: (environmentId: string) => void;
}) {
  const { t } = useTranslation();
  const environnements = useEnvironments();
  const creation = useCreateEnvironment();
  // `useId` et non un identifiant fixe : plusieurs demandes ouvrent leur choix en même
  // temps, et deux `id` identiques feraient pointer le libellé de l'une sur le champ de
  // l'autre — une liste déroulante qu'on croit remplir et qui ne bouge pas.
  const champ = useId();
  const [ouvreCreation, setOuvreCreation] = useState(false);
  const [selection, setSelection] = useState(choisi ?? "");

  // Un environnement DÉJÀ APPARIÉ n'est pas proposé : deux stacks pour un même
  // environnement, et « à quelle stack appartient ce device » n'a plus de réponse unique.
  // Celui qu'on a déjà désigné reste dans la liste, même si une course vient de l'apparier
  // ailleurs : le retirer ferait disparaître le choix affiché sans rien dire, et le
  // serveur refusera en le nommant.
  const offerts = (environnements.data ?? []).filter(
    (environnement: Environment) =>
      environnement.paired_base_url === null || environnement.id === choisi,
  );

  if (ouvreCreation) {
    return (
      <div className="row-detail">
        <p className="help">{t("pairing.designation.createHelp")}</p>
        <EnvironmentForm
          idPrefix={champ}
          label=""
          slug=""
          submitLabel={t("pairing.designation.createSubmit")}
          pending={creation.isPending}
          error={creation.isError ? creation.error : null}
          onSubmit={(input) =>
            creation.mutate(input, {
              onSuccess: (environnement) => {
                setOuvreCreation(false);
                // La demande s'y rattache AUSSITÔT (critère 3) : un environnement créé
                // puis laissé non désigné ferait croire le geste terminé alors que le
                // code n'est toujours pas révélable.
                onChoose(environnement.id);
              },
            })
          }
          onCancel={() => setOuvreCreation(false)}
        />
      </div>
    );
  }

  return (
    <div className="row-detail">
      <div className="field">
        <label htmlFor={champ}>{t("pairing.designation.label")}</label>
        <select
          id={champ}
          value={selection}
          onChange={(event) => setSelection(event.target.value)}
        >
          <option value="">{t("pairing.designation.none")}</option>
          {offerts.map((environnement) => (
            <option key={environnement.id} value={environnement.id}>
              {environnement.label} ({environnement.slug})
            </option>
          ))}
        </select>
        <p className="help">{t("pairing.designation.help")}</p>
      </div>
      {error !== null && error !== undefined && (
        <p className="alert alert-danger" role="alert">
          {t(designationRefusKey(error))}
        </p>
      )}
      <div className="actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={pending || selection === "" || selection === choisi}
          onClick={() => onChoose(selection)}
        >
          {submitLabel}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setOuvreCreation(true)}
        >
          {t("pairing.designation.create")}
        </button>
      </div>
    </div>
  );
}

