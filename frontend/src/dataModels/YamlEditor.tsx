import Editor from "@monaco-editor/react";
import { useTranslation } from "react-i18next";

import { MODEL_URI_SUFFIX } from "./monaco";

/** Le YAML du schéma dans Monaco, complété et vérifié à la frappe par monaco-yaml. */
export default function YamlEditor({
  path,
  value,
  onChange,
  readOnly,
}: {
  path: string;
  value: string;
  onChange: (value: string) => void;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="yaml-editor" aria-label={t("dataModels.fields.content")} role="group">
      <Editor
        height="560px"
        language="yaml"
        // Le motif du fichier rattache le méta-schéma (voir monaco.ts).
        path={`${path}${MODEL_URI_SUFFIX}`}
        value={value}
        onChange={(next) => onChange(next ?? "")}
        options={{ readOnly, minimap: { enabled: false }, tabSize: 2, scrollBeyondLastLine: false }}
      />
    </div>
  );
}
