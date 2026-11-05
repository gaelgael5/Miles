import type { JsonSchema } from "jsonjoy-builder";
import { useTranslation } from "react-i18next";

import { type RootField, offerable, rootFields, toggled, usageOf, withUsage } from "./fieldUsage";

/**
 * L'utilité des champs d'un modèle (Gael, 05/11/2026) : ce qui identifie un objet, et ce
 * qui se montre dans le tableau du module d'environnement.
 *
 * La liste des champs ne se modifie PAS ici : elle est celle du modèle, et elle suit
 * l'éditeur. Un ajout de champ à cet écran aurait été un deuxième endroit où décrire le
 * modèle, et les deux auraient divergé dès la première description écrite d'un seul côté.
 *
 * Premier niveau seulement (Gael) : c'est l'identité et la lecture d'un objet qu'on
 * déclare, pas un chemin de filtre. Les propriétés profondes restent celles que la page
 * d'un storage coche dans l'arbre.
 */
export function FieldUsage({
  schema,
  readOnly,
  onChange,
}: {
  schema: JsonSchema;
  readOnly: boolean;
  onChange: (schema: JsonSchema) => void;
}) {
  const { t } = useTranslation();
  const fields = rootFields(schema);
  const usage = usageOf(schema);

  function toggle(which: "key" | "columns", path: string) {
    onChange(withUsage(schema, { ...usage, [which]: toggled(usage[which], path) }));
  }

  if (fields.length === 0) {
    return (
      <div className="card">
        <p className="help">{t("dataModels.usage.none")}</p>
      </div>
    );
  }
  return (
    <div className="card">
      <p className="help">{t("dataModels.usage.intro")}</p>
      <section className="card-list" aria-label={t("dataModels.usage.table")}>
        <div className="row-head row-columns">
          <div className="cell-auto cell-key">{t("dataModels.usage.field")}</div>
          <div className="cell-auto">{t("dataModels.usage.key")}</div>
          <div className="cell-auto">{t("dataModels.usage.column")}</div>
        </div>
        <ul className="plain-list">
          {fields.map((field) => (
            <li key={field.name} className="row row-compact row-columns">
              <div className="cell-auto cell-key">
                <span className="mono">{field.name}</span>{" "}
                <span className="caption">{describe(field)}</span>
              </div>
              <Case
                field={field}
                checked={usage.key.includes(field.path)}
                label={t("dataModels.usage.keyOf", { field: field.name })}
                readOnly={readOnly}
                onToggle={() => toggle("key", field.path)}
              />
              <Case
                field={field}
                checked={usage.columns.includes(field.path)}
                label={t("dataModels.usage.columnOf", { field: field.name })}
                readOnly={readOnly}
                onToggle={() => toggle("columns", field.path)}
              />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function describe(field: RootField): string {
  return field.reference ? "$ref" : field.type;
}

/**
 * Une case, ou la raison de son absence.
 *
 * Un objet, un tableau ou un renvoi vers un autre modèle ne porte pas UNE valeur : le
 * module d'environnement refuserait la colonne. Même règle que l'arbre des storages — on
 * ne propose que ce qui marche, plutôt que de laisser découvrir le refus après coup.
 */
function Case({
  field,
  checked,
  label,
  readOnly,
  onToggle,
}: {
  field: RootField;
  checked: boolean;
  label: string;
  readOnly: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  if (!offerable(field)) {
    return <div className="cell-auto caption">{t("dataModels.usage.unusable")}</div>;
  }
  return (
    <div className="cell-auto">
      <input
        type="checkbox"
        aria-label={label}
        checked={checked}
        disabled={readOnly}
        onChange={onToggle}
      />
    </div>
  );
}
