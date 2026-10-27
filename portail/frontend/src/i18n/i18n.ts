import { i18n, initI18n } from "@miles/socle-web";

import enUS from "./locales/en-US.json";
import frFR from "./locales/fr-FR.json";

/**
 * Câblage des libellés du portail sur l'instance i18next du socle.
 *
 * Chaque produit a ce module, et c'est le seul endroit où ses libellés rencontrent ceux
 * du socle : importer ce fichier initialise i18next. Les espaces de noms `app` et
 * `profile` sont partagés — le socle porte la marque et l'identité, le portail son
 * sous-titre, son menu et ses sections de profil.
 */
initI18n({ "en-US": enUS, "fr-FR": frFR });

export { applyLanguage, FALLBACK_CULTURE, UI_LANGUAGES } from "@miles/socle-web";
export default i18n;
