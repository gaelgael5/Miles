import "@testing-library/jest-dom/vitest";
import "./i18n/i18n";

// Monaco ne tourne pas dans jsdom (travailleurs, mise en page) : une zone de texte tient
// sa place partout, avec le même contrat que l'éditeur YAML (story e38806f3).
vi.mock("./dataModels/monaco", () => ({ MODEL_URI_SUFFIX: ".schema.yaml" }));
vi.mock("./dataModels/YamlEditor", () => import("./test/YamlEditorStub"));
vi.mock("./dataModels/JsltEditor", () => import("./test/JsltEditorStub"));
// Swagger UI non plus : il mesure et dessine, ce que jsdom ne fait pas.
vi.mock("./contracts/SwaggerView", () => import("./test/SwaggerViewStub"));
// jsdom ne calcule aucune mise en page, donc n'implémente pas `ResizeObserver`. La
// doublure ne mesure rien et n'appelle jamais : c'est exact, il n'y a rien à observer.
// Le placement de la gouttière, lui, se teste sur `editorMetrics`, où les rectangles
// sont posés explicitement.
globalThis.ResizeObserver = class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
};
