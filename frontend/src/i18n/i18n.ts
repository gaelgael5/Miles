import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import enUS from "./locales/en-US.json";
import frFR from "./locales/fr-FR.json";

// en-US est le repli imposé par le cadrage : toujours active, jamais désactivable.
export const FALLBACK_CULTURE = "en-US";

void i18n.use(initReactI18next).init({
  resources: { "en-US": { translation: enUS }, "fr-FR": { translation: frFR } },
  lng: FALLBACK_CULTURE,
  fallbackLng: FALLBACK_CULTURE,
  interpolation: { escapeValue: false },
});

export default i18n;
