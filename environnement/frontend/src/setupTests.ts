import "@testing-library/jest-dom/vitest";

// Initialise i18next avec les libellés du socle ET ceux du produit, comme main.tsx.
import "./i18n/i18n";

// Swagger UI ne tourne pas sous jsdom : il mesure et dessine. La doublure rend le
// document qu'on lui donne, ce qui est précisément ce que les tests vérifient.
vi.mock("./ingestion/SwaggerView", () => import("./test/SwaggerViewStub"));
