import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enUS from "./locales/en-US.json";
import frFR from "./locales/fr-FR.json";

// en-US est le repli imposé par le cadrage : toujours active, jamais désactivable.
export const FALLBACK_CULTURE = "en-US";

void i18n.use(initReactI18next).init({
  // Garder PORTAL_LANGUAGES aligné : c'est la liste que le profil propose.
  resources: { "en-US": { translation: enUS }, "fr-FR": { translation: frFR } },
  lng: FALLBACK_CULTURE,
  fallbackLng: FALLBACK_CULTURE,
  interpolation: { escapeValue: false },
});

/** Cultures pour lesquelles le portail a une traduction ; les autres retombent sur en-US. */
export const PORTAL_LANGUAGES: readonly string[] = ["en-US", "fr-FR"];

/** Affiche le portail dans cette culture si elle est traduite, sinon en en-US (repli visible). */
export function applyLanguage(code: string | null | undefined): void {
  const target = code && PORTAL_LANGUAGES.includes(code) ? code : FALLBACK_CULTURE;
  if (i18n.language !== target) {
    void i18n.changeLanguage(target);
  }
}

export default i18n;
