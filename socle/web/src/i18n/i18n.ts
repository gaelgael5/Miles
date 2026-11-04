import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import socleEnUS from "./locales/en-US.json";
import socleFrFR from "./locales/fr-FR.json";

// en-US est le repli imposé par le cadrage : toujours active, jamais désactivable.
export const FALLBACK_CULTURE = "en-US";

/** Cultures pour lesquelles l'IHM a une traduction ; les autres retombent sur en-US. */
export const UI_LANGUAGES: readonly string[] = ["en-US", "fr-FR"];

/** Libellés propres à un produit, par culture : ceux que le socle ne porte pas. */
export type ProductLocales = Readonly<Record<string, object>>;

const SOCLE_LOCALES: ProductLocales = { "en-US": socleEnUS, "fr-FR": socleFrFR };

type Tree = { [key: string]: unknown };

/**
 * Fusion en profondeur, et non un simple étalement : les espaces de noms `app` et
 * `profile` sont PARTAGÉS — le socle y porte la marque, l'amorçage et l'identité, le
 * produit son sous-titre, son menu et ses propres sections. Un étalement de premier
 * niveau ferait disparaître la moitié du socle au profit de celle du produit.
 */
function merge(base: Tree, overlay: Tree): Tree {
  const fusion: Tree = { ...base };
  for (const [key, value] of Object.entries(overlay)) {
    const existant = fusion[key];
    const deuxArbres =
      typeof existant === "object" && existant !== null && !Array.isArray(existant) &&
      typeof value === "object" && value !== null && !Array.isArray(value);
    fusion[key] = deuxArbres ? merge(existant as Tree, value as Tree) : value;
  }
  return fusion;
}

/**
 * Initialise l'instance i18next partagée, les libellés du produit par-dessus ceux du socle.
 *
 * Divergence volontaire avec ce que faisait le portail : l'initialisation était un effet
 * de bord de l'import du module, ce qui était possible quand les libellés étaient tous
 * dans le même dépôt de code. Le socle ne connaît pas les libellés de son consommateur,
 * donc c'est le produit qui déclenche l'initialisation en les apportant.
 */
export function initI18n(produit: ProductLocales): void {
  const resources: Record<string, { translation: object }> = {};
  for (const culture of UI_LANGUAGES) {
    const socle = (SOCLE_LOCALES[culture] ?? {}) as Tree;
    resources[culture] = { translation: merge(socle, (produit[culture] ?? {}) as Tree) };
  }
  void i18n.use(initReactI18next).init({
    resources,
    lng: FALLBACK_CULTURE,
    fallbackLng: FALLBACK_CULTURE,
    interpolation: { escapeValue: false },
  });
}

/** Affiche l'IHM dans cette culture si elle est traduite, sinon en en-US (repli visible). */
export function applyLanguage(code: string | null | undefined): void {
  const target = code && UI_LANGUAGES.includes(code) ? code : FALLBACK_CULTURE;
  if (i18n.language !== target) {
    void i18n.changeLanguage(target);
  }
}

export default i18n;
