import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  MAX_LIST_DEPTH,
  type ModelDoc,
  PROPERTY_RE,
  type PropertyNode,
  TYPES,
  type TypeSpec,
  addProperty,
  removeProperty,
  retype,
  setSpec,
  updateProperty,
} from "./modelTree";

type Edit = (spec: TypeSpec) => void;

/** Les valeurs d'une énumération, séparées par des virgules : saisies comme on les dit. */
function EnumValues({ values, onChange, readOnly }: { values: string[]; onChange: (v: string[]) => void; readOnly: boolean }) {
  const { t } = useTranslation();
  // Texte local : « a, » en cours de frappe ne doit pas perdre sa virgule. Le composant
  // est remonté quand le YAML est relu (identifiants neufs), il ne garde rien de périmé.
  const [text, setText] = useState(values.join(", "));
  return (
    <label className="field">
      {t("dataModels.tree.values")}
      <input
        readOnly={readOnly}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          onChange(e.target.value.split(",").map((v) => v.trim()).filter((v) => v !== ""));
        }}
      />
    </label>
  );
}

function TypeEditor({
  spec,
  onChange,
  models,
  depth,
  readOnly,
}: {
  spec: TypeSpec;
  onChange: Edit;
  models: string[];
  depth: number;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  // Même borne que la grammaire : au-delà, une liste n'est plus proposée.
  const offered = TYPES.filter((type) => type !== "liste" || depth < MAX_LIST_DEPTH);
  const targets = spec.modele && !models.includes(spec.modele) ? [spec.modele, ...models] : models;
  return (
    <div className="tree-type">
      <label className="field">
        {t("dataModels.tree.type")}
        <select
          disabled={readOnly}
          value={spec.type}
          onChange={(e) => onChange(retype(e.target.value as TypeSpec["type"]))}
        >
          {offered.map((type) => (
            <option key={type} value={type}>
              {t(`dataModels.types.${type}`)}
            </option>
          ))}
        </select>
      </label>
      {spec.type === "enumeration" && (
        <EnumValues
          values={spec.valeurs ?? []}
          readOnly={readOnly}
          onChange={(valeurs) => onChange({ ...spec, valeurs })}
        />
      )}
      {spec.type === "objet" && (
        <label className="field">
          {t("dataModels.tree.model")}
          <select
            disabled={readOnly}
            value={spec.modele ?? ""}
            onChange={(e) => onChange({ ...spec, modele: e.target.value })}
          >
            <option value="">{t("dataModels.tree.chooseModel")}</option>
            {targets.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      )}
      {spec.type === "liste" && (
        <div className="tree-nested">
          <div className="caption">{t("dataModels.tree.elements")}</div>
          <TypeEditor
            spec={spec.elements ?? { type: "chaine" }}
            onChange={(elements) => onChange({ ...spec, elements })}
            models={models}
            depth={depth + 1}
            readOnly={readOnly}
          />
        </div>
      )}
    </div>
  );
}

function PropertyRow({
  doc,
  node,
  onChange,
  models,
  readOnly,
}: {
  doc: ModelDoc;
  node: PropertyNode;
  onChange: (doc: ModelDoc) => void;
  models: string[];
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(node.name);
  const taken = doc.proprietes.some((p) => p.id !== node.id && p.name === name);
  const invalid = !PROPERTY_RE.test(name) || taken;

  function rename(value: string) {
    setName(value);
    // Un nom invalide ou déjà pris n'entre pas dans le modèle : deux clés identiques
    // se fondraient en une au YAML, et l'une disparaîtrait sans bruit.
    const free = !doc.proprietes.some((p) => p.id !== node.id && p.name === value);
    if (PROPERTY_RE.test(value) && free) onChange(updateProperty(doc, node.id, { name: value }));
  }

  return (
    <li className="tree-node">
      <div className="field-row">
        <label className="field">
          {t("dataModels.tree.name")}
          <input
            className="mono"
            readOnly={readOnly}
            aria-invalid={invalid}
            value={name}
            onChange={(e) => rename(e.target.value)}
          />
        </label>
        <label className="field-check">
          <input
            type="checkbox"
            disabled={readOnly}
            checked={node.obligatoire}
            onChange={(e) => onChange(updateProperty(doc, node.id, { obligatoire: e.target.checked }))}
          />
          {t("dataModels.tree.required")}
        </label>
        {!readOnly && (
          <button
            type="button"
            className="btn btn-danger"
            onClick={() => onChange(removeProperty(doc, node.id))}
          >
            {t("dataModels.tree.remove")}
          </button>
        )}
      </div>
      {invalid && (
        <p className="alert" role="alert">
          {t(taken ? "dataModels.tree.nameTaken" : "dataModels.tree.nameInvalid")}
        </p>
      )}
      <TypeEditor
        spec={node}
        models={models}
        depth={0}
        readOnly={readOnly}
        onChange={(spec) => onChange(setSpec(doc, node.id, spec))}
      />
    </li>
  );
}

/**
 * L'arbre des propriétés (story 7208ba06) : modifier un modèle sans connaître la syntaxe.
 * Tout reste en mémoire ; seul « Enregistrer » écrit, et le serveur arbitre la grammaire.
 */
export function ModelTree({
  doc,
  onChange,
  models,
  readOnly,
}: {
  doc: ModelDoc;
  onChange: (doc: ModelDoc) => void;
  models: string[];
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="tree" aria-label={t("dataModels.tree.title")} role="group">
      <div className="field-row">
        <label className="field">
          {t("dataModels.tree.version")}
          <input
            type="number"
            min={1}
            readOnly={readOnly}
            value={doc.version}
            onChange={(e) => onChange({ ...doc, version: Number(e.target.value) })}
          />
        </label>
        <label className="field">
          {t("dataModels.tree.description")}
          <input
            readOnly={readOnly}
            value={doc.description ?? ""}
            onChange={(e) => onChange({ ...doc, description: e.target.value })}
          />
        </label>
      </div>
      {doc.proprietes.length === 0 && <p className="muted">{t("dataModels.tree.empty")}</p>}
      <ul className="plain-list">
        {doc.proprietes.map((node) => (
          <PropertyRow
            key={node.id}
            doc={doc}
            node={node}
            onChange={onChange}
            models={models}
            readOnly={readOnly}
          />
        ))}
      </ul>
      {!readOnly && (
        <div className="actions">
          <button type="button" className="btn btn-secondary" onClick={() => onChange(addProperty(doc))}>
            {t("dataModels.tree.add")}
          </button>
        </div>
      )}
    </div>
  );
}
