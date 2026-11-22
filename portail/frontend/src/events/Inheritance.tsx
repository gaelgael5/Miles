import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SHARED_SCOPE } from "../api/dataModels";
import type { WorkTarget } from "../api/workTarget";
import { type EventType, useRedirectInheritance } from "../api/workflowEvents";
import { ModelRefusal } from "../workspaces/ModelRefusal";

/**
 * L'héritage d'un type d'event : de qui il dérive, et la redirection de ce lien.
 *
 * Gael, le 19/11/2026 : « quand on créé un second event, il herite de ce premier event.
 * l'affichage de l'héritage apparait en bas. cet heritage peut être redirigé sur un autre
 * event présent sur le disque. »
 *
 * Ce lien n'est pas un dispositif de Miles : c'est le `allOf: $ref` du modèle du payload,
 * la composition de JSON Schema. L'écran n'a donc rien à recomposer — il compare le chemin
 * du parent au `model` des autres types.
 */

/** La valeur du choix « l'event de base » : aucun parent, donc aucun renvoi écrit. */
export const BASE = "";
/** Le parent actuel n'est le payload d'aucun type d'event : montré, et non sélectionnable. */
const OTHER = "__other";

/** Le type d'event dont `declared` hérite, s'il y en a un parmi ceux de la branche. */
export function parentOf(types: EventType[], declared: EventType): EventType | undefined {
  const [first] = declared.parents;
  return first === undefined ? undefined : types.find((other) => other.model === first);
}

/**
 * Les types dont `declared` peut hériter : visibles de son périmètre, lui-même exclu.
 *
 * Même règle de portée que le serveur et que les modèles entre eux — ici, c'est pour ne
 * pas proposer ce qui serait refusé. Les CYCLES, eux, ne sont pas filtrés ici : le serveur
 * en est seul arbitre, et son refus nomme la boucle. Les calculer deux fois aurait fait
 * deux règles à tenir d'accord.
 */
export function eligibleParents(types: EventType[], scope: string, name?: string): EventType[] {
  return types.filter(
    (other) =>
      !(other.scope === scope && other.name === name) &&
      (other.scope === SHARED_SCOPE || (scope !== SHARED_SCOPE && other.scope === scope)),
  );
}

/** Le choix d'un parent : l'event de base, ou un autre type d'event. */
export function ParentSelect({
  label,
  types,
  value,
  unknownParent,
  onChange,
}: {
  label: string;
  types: EventType[];
  value: string;
  /** Chemin du modèle parent quand il n'est le payload d'aucun type : montré tel quel. */
  unknownParent?: string;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <label className="field">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value={BASE}>{t("workflowEvents.inherit.base")}</option>
        {unknownParent !== undefined && (
          <option value={OTHER} disabled>
            {t("workflowEvents.inherit.unknownParent", { path: unknownParent })}
          </option>
        )}
        {types.map((other) => (
          <option key={`${other.scope}/${other.name}`} value={`${other.scope}/${other.name}`}>
            {other.label} — {other.name}
          </option>
        ))}
      </select>
    </label>
  );
}

/** `scope/name` tel que le `<select>` le porte, retourné en couple pour la route. */
export function parentPair(value: string): { scope: string; name: string } | undefined {
  if (value === BASE || value === OTHER) {
    return undefined;
  }
  const [scope = "", name = ""] = value.split("/");
  return { scope, name };
}

/**
 * EN BAS d'un type d'event : de qui il hérite, et vers qui le rediriger.
 *
 * Le bouton n'est actif que si le choix a changé : rediriger vers le parent déjà en place
 * écrirait un commit qui ne change rien.
 */
export function InheritanceBlock({
  target,
  types,
  declared,
}: {
  target: WorkTarget;
  /** TOUS les types de la branche : un parent peut vivre dans un autre périmètre. */
  types: EventType[];
  declared: EventType;
}) {
  const { t } = useTranslation();
  const redirect = useRedirectInheritance(target);
  const parent = parentOf(types, declared);
  const [first] = declared.parents;
  const unknown = first !== undefined && parent === undefined ? first : undefined;
  const current = parent === undefined ? (unknown === undefined ? BASE : OTHER) : `${parent.scope}/${parent.name}`;
  const [choice, setChoice] = useState(current);

  return (
    <div className="row-detail row-inherit">
      <p className="help">
        {unknown !== undefined
          ? t("workflowEvents.inherit.fromModel", { path: unknown })
          : parent === undefined
            ? t("workflowEvents.inherit.fromBase")
            : t("workflowEvents.inherit.fromEvent", { label: parent.label, name: parent.name })}
      </p>
      {!target.readOnly && (
        <div className="actions">
          <ParentSelect
            label={t("workflowEvents.inherit.redirect")}
            types={eligibleParents(types, declared.scope, declared.name)}
            value={choice}
            unknownParent={unknown}
            onChange={setChoice}
          />
          <button
            type="button"
            className="btn btn-secondary"
            disabled={choice === current || redirect.isPending}
            onClick={() =>
              redirect.mutate({
                scope: declared.scope,
                name: declared.name,
                parent: parentPair(choice),
              })
            }
          >
            {t("workflowEvents.inherit.submit")}
          </button>
        </div>
      )}
      {redirect.isError && <ModelRefusal error={redirect.error} />}
    </div>
  );
}
