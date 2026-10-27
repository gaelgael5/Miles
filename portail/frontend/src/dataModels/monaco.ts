import { loader } from "@monaco-editor/react";
import "monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution.js";
// JSON sert à coller un échantillon dans l'import intelligent : coloration et
// repérage des erreurs de syntaxe, rien d'autre — le schéma reste du YAML.
import "monaco-editor/esm/vs/language/json/monaco.contribution.js";
import * as monaco from "monaco-editor/esm/vs/editor/editor.api.js";
import { configureMonacoYaml } from "monaco-yaml";

import draft07 from "./json-schema-draft-07.json";

/**
 * Monaco servi par le portail lui-même (story e38806f3) : jamais depuis un CDN, que le
 * chargeur de @monaco-editor/react interroge sinon. Ce module n'est importé que par
 * l'écran d'édition d'un modèle, chargé à la demande : le reste du portail ne le paie pas.
 */
// Travailleurs construits ici, à l'appel : avec les classes `?worker` de Vite, l'ordre
// d'évaluation des morceaux les laissait indéfinies quand Monaco les demandait, et Monaco
// retombait sur le fil principal, sans service YAML (constaté dans Chromium, 23/10/2026).
self.MonacoEnvironment = {
  getWorker(_moduleId: string, label: string) {
    if (label === "yaml") {
      return new Worker(new URL("./yaml.worker.ts", import.meta.url), { type: "module" });
    }
    if (label === "json") {
      return new Worker(
        new URL("monaco-editor/esm/vs/language/json/json.worker.js", import.meta.url),
        { type: "module" },
      );
    }
    return new Worker(new URL("monaco-editor/esm/vs/editor/editor.worker.js", import.meta.url), {
      type: "module",
    });
  },
};

loader.config({ monaco });
// Monaco tenu en 0.52 (package.json « ~0.52.2 »), exprès : à partir de 0.53,
// `editor.createWebWorker` attend un `worker` tout fait, alors que monaco-yaml 5.5 lui
// passe encore `moduleId` et `label` — Monaco ne créait alors aucun travailleur YAML,
// et l'édition du YAML levait des erreurs en boucle (constaté dans Chromium, 23/10/2026).

export const MODEL_URI_SUFFIX = ".schema.yaml";

// Aide à la saisie seulement (complétion, survol) : monaco-yaml ne lit bien que les
// méta-schémas en un seul document, et celui de 2020-12 en compte huit. L'arbitre reste
// le serveur, qui valide en 2020-12 (story 0f7cda10).
configureMonacoYaml(monaco, {
  enableSchemaRequest: false,
  schemas: [{ fileMatch: [`**/*${MODEL_URI_SUFFIX}`], uri: "miles:/meta/json-schema", schema: draft07 }],
});
