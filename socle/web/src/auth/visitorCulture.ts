const STORAGE_KEY = "miles.loginCulture";
export const FALLBACK = "en-US";

/** Choix mémorisé sur ce navigateur ; le stockage peut être refusé (navigation privée). */
export function readStoredCulture(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeCulture(code: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, code);
  } catch {
    // Choix non mémorisé : il vaut pour cette page, et c'est un confort, pas un droit.
  }
}

/**
 * Culture du visiteur (décision du 20/10/2026) : son choix mémorisé s'il est encore actif,
 * sinon la langue du navigateur ramenée à une culture active, sinon en-US.
 * « fr-CA » non active retombe sur une culture active de même langue, « fr-FR » par exemple.
 */
export function resolveVisitorCulture(
  active: readonly string[],
  browserLanguages: readonly string[],
  stored: string | null,
): string {
  const byLower = new Map(active.map((code) => [code.toLowerCase(), code]));
  if (stored !== null && byLower.has(stored.toLowerCase())) {
    return byLower.get(stored.toLowerCase()) ?? FALLBACK;
  }
  for (const language of browserLanguages) {
    const exact = byLower.get(language.toLowerCase());
    if (exact !== undefined) {
      return exact;
    }
    const base = language.split("-")[0]?.toLowerCase();
    const sameLanguage = active.find((code) => code.split("-")[0]?.toLowerCase() === base);
    if (sameLanguage !== undefined) {
      return sameLanguage;
    }
  }
  return FALLBACK;
}
