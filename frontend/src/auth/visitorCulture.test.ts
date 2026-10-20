import { resolveVisitorCulture } from "./visitorCulture";

const ACTIVE = ["en-US", "fr-FR", "de-DE"];

describe("resolveVisitorCulture", () => {
  it("prefers the remembered choice while it is still active", () => {
    expect(resolveVisitorCulture(ACTIVE, ["fr-FR"], "de-DE")).toBe("de-DE");
    expect(resolveVisitorCulture(ACTIVE, ["fr-FR"], "ja-JP")).toBe("fr-FR");
  });

  it("follows the browser, exactly or by language, case aside", () => {
    expect(resolveVisitorCulture(ACTIVE, ["fr-fr"], null)).toBe("fr-FR");
    expect(resolveVisitorCulture(ACTIVE, ["fr-CA", "en-US"], null)).toBe("fr-FR");
    expect(resolveVisitorCulture(ACTIVE, ["ja-JP", "de"], null)).toBe("de-DE");
  });

  it("falls back to en-US when nothing matches or nothing is known", () => {
    expect(resolveVisitorCulture(ACTIVE, ["ja-JP"], null)).toBe("en-US");
    expect(resolveVisitorCulture([], ["fr-FR"], "fr-FR")).toBe("en-US");
    expect(resolveVisitorCulture(ACTIVE, [], null)).toBe("en-US");
  });
});
