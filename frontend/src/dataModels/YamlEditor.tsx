import Editor from "@monaco-editor/react";
import { useTranslation } from "react-i18next";

import { MODEL_URI_SUFFIX } from "./monaco";

/** Monaco pour le YAML du schéma, complété et vérifié à la frappe par monaco-yaml.
 *
 * Sert aussi à coller un échantillon JSON dans l'import intelligent : d'où `language`
 * et `height`, plutôt qu'un second éditeur à câbler et à stubber. */
export default function YamlEditor({
  path,
  value,
  onChange,
  readOnly,
  language = "yaml",
  height = "560px",
  ariaLabel,
  attachMetaSchema = true,
}: {
  path: string;
  value: string;
  onChange: (value: string) => void;
  readOnly: boolean;
  language?: "yaml" | "json";
  height?: string;
  ariaLabel?: string;
  // Un ÉCHANTILLON n'est pas un schéma : lui rattacher le méta-schéma le ferait
  // signaler comme non conforme à chaque frappe, pour rien.
  attachMetaSchema?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="yaml-editor"
      aria-label={ariaLabel ?? t("dataModels.fields.content")}
      role="group"
    >
      <Editor
        height={height}
        language={language}
        // Le motif du fichier rattache le méta-schéma (voir monaco.ts).
        path={attachMetaSchema ? `${path}${MODEL_URI_SUFFIX}` : path}
        value={value}
        onChange={(next) => onChange(next ?? "")}
        options={{ readOnly, minimap: { enabled: false }, tabSize: 2, scrollBeyondLastLine: false }}
      />
    </div>
  );
}
