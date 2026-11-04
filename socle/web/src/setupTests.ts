import "@testing-library/jest-dom/vitest";

import { initI18n } from "./i18n/i18n";

// Les tests du socle tournent sans produit : seuls ses propres libellés sont chargés.
// Un produit, lui, appelle initI18n avec les siens par-dessus (voir son i18n/i18n.ts).
initI18n({});
