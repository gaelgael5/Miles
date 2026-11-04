import enUS from "./locales/en-US.json";
import frFR from "./locales/fr-FR.json";

function keysOf(tree: object, prefix = ""): string[] {
  return Object.entries(tree).flatMap(([key, value]) =>
    typeof value === "object" && value !== null
      ? keysOf(value as object, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  );
}

describe("locales du module d'environnement", () => {
  it("every culture carries exactly the keys of the en-US fallback", () => {
    expect(keysOf(frFR).sort()).toEqual(keysOf(enUS).sort());
  });
});
