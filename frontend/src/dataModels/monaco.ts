import { loader } from "@monaco-editor/react";
import "monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution.js";
import * as monaco from "monaco-editor/esm/vs/editor/editor.api.js";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker.js?worker";
import { configureMonacoYaml } from "monaco-yaml";

import draft07 from "./json-schema-draft-07.json";
import YamlWorker from "./yaml.worker.ts?worker";

/**
 * Monaco servi par le portail lui-même (story e38806f3) : jamais depuis un CDN, que le
 * chargeur de @monaco-editor/react interroge sinon. Ce module n'est importé que par
 * l'écran d'édition d'un modèle, chargé à la demande : le reste du portail ne le paie pas.
 */
self.MonacoEnvironment = {
  getWorker(_moduleId: string, label: string) {
    return label === "yaml" ? new YamlWorker() : new EditorWorker();
  },
};

loader.config({ monaco });

export const MODEL_URI_SUFFIX = ".schema.yaml";

// Aide à la saisie seulement (complétion, survol) : monaco-yaml ne lit bien que les
// méta-schémas en un seul document, et celui de 2020-12 en compte huit. L'arbitre reste
// le serveur, qui valide en 2020-12 (story 0f7cda10).
configureMonacoYaml(monaco, {
  enableSchemaRequest: false,
  schemas: [{ fileMatch: [`**/*${MODEL_URI_SUFFIX}`], uri: "miles:/meta/json-schema", schema: draft07 }],
});
