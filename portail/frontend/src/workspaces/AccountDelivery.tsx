import { useTranslation } from "react-i18next";

import type { Delivery } from "../api/accounts";
import { useModelPaths } from "../api/dataModels";
import type { WorkTarget } from "../api/workTarget";
import { selectable } from "./ModelPathTree";

/** « shared/compte » → les deux morceaux que la route des chemins attend. */
export function modelParts(model: string | null): { scope: string | null; name: string | null } {
  const cut = model === null ? -1 : model.indexOf("/");
  if (model === null || cut <= 0 || cut === model.length - 1) {
    // `null` des deux côtés : `useModelPaths` n'interroge alors pas le serveur, plutôt
    // que de lui demander les chemins d'un modèle dont on ne connaît pas le nom.
    return { scope: null, name: null };
  }
  return { scope: model.slice(0, cut), name: model.slice(cut + 1) };
}

/**
 * Le mode d'envoi du code d'enregistrement, et le champ du compte qui porte l'adresse
 * (Gael, 31/10/2026) : « une fois le stockage sélectionné, il faut identifier le mode
 * d'enregistrement […] une fois le mode sélectionné il faut choisir le champ qui
 * contient l'adresse d'envoi ».
 *
 * Le champ se CHOISIT dans les propriétés du modèle, il ne se tape pas : un jpath saisi
 * à la main désignerait une propriété qui n'existe pas, et l'erreur n'apparaîtrait qu'au
 * premier terminal réel.
 */
export function AccountDelivery({
  target,
  model,
  modes,
  served,
  value,
  readOnly,
  onChange,
}: {
  target: WorkTarget;
  /** Le modèle que déclare le stockage retenu ; null, on ne sait pas quoi proposer. */
  model: string | null;
  modes: string[];
  served: string[];
  value: Delivery | null;
  readOnly: boolean;
  onChange: (delivery: Delivery | null) => void;
}) {
  const { t } = useTranslation();
  const { scope, name } = modelParts(model);
  const paths = useModelPaths(target, scope, name);
  const fields = (paths.data?.paths ?? []).filter((p) => selectable(p.type, p.path));
  const mode = value?.mode ?? "";
  const field = value?.field ?? "";

  return (
    <>
      <label>
        {t("accounts.fields.mode")}
        <select
          value={mode}
          disabled={readOnly || model === null}
          onChange={(event) => {
            const picked = event.target.value;
            // Vider le mode retire l'envoi ENTIER : un champ d'adresse sans mode ne dit
            // pas comment envoyer, et le serveur le refuserait.
            onChange(picked === "" ? null : { mode: picked, field });
          }}
        >
          <option value="">{t("accounts.choose")}</option>
          {modes.map((m) => (
            // Les modes non servis restent VISIBLES et désactivés : les cacher ferait
            // croire que le produit ne les prévoit pas, alors qu'ils sont décidés et
            // pas encore construits (« pour le moment on implémentera que le mail »).
            <option key={m} value={m} disabled={!served.includes(m)}>
              {served.includes(m)
                ? t(`accounts.modes.${m}`)
                : t("accounts.modeNotServed", { mode: t(`accounts.modes.${m}`) })}
            </option>
          ))}
        </select>
      </label>

      {mode !== "" && (
        <label>
          {t("accounts.fields.addressField")}
          <select
            value={field}
            disabled={readOnly}
            onChange={(event) => onChange({ mode, field: event.target.value })}
          >
            <option value="">{t("accounts.choose")}</option>
            {fields.map((p) => (
              <option key={p.path} value={p.path}>
                {p.path}
              </option>
            ))}
          </select>
        </label>
      )}
      {mode !== "" && paths.isSuccess && fields.length === 0 && (
        // Une liste vide sans explication laisserait chercher ce qui ne va pas : c'est
        // que le modèle des comptes n'a aucune propriété simple à prendre pour adresse.
        <p className="alert">{t("accounts.noField", { model })}</p>
      )}
      {mode !== "" && <p className="help">{t("accounts.addressHelp")}</p>}
    </>
  );
}
