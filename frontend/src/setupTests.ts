import "@testing-library/jest-dom/vitest";
import "./i18n/i18n";

// Monaco ne tourne pas dans jsdom (travailleurs, mise en page) : une zone de texte tient
// sa place partout, avec le même contrat que l'éditeur YAML (story e38806f3).
vi.mock("./dataModels/monaco", () => ({ MODEL_URI_SUFFIX: ".schema.yaml" }));
vi.mock("./dataModels/YamlEditor", () => import("./test/YamlEditorStub"));
vi.mock("./dataModels/JsltEditor", () => import("./test/JsltEditorStub"));
