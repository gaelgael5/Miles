import { i18n, initI18n } from "@miles/socle-web";

import enUS from "./locales/en-US.json";
import frFR from "./locales/fr-FR.json";

/**
 * Câblage des libellés du module d'environnement sur l'instance i18next du socle.
 *
 * Chaque produit a ce module, et c'est le seul endroit où ses libellés rencontrent ceux
 * du socle : importer ce fichier initialise i18next. L'espace `app` est partagé — le
 * socle porte la marque et les libellés d'authentification, le produit son sous-titre
 * et son menu.
 */
initI18n({ "en-US": enUS, "fr-FR": frFR });

export { applyLanguage, FALLBACK_CULTURE, UI_LANGUAGES } from "@miles/socle-web";
export default i18n;
