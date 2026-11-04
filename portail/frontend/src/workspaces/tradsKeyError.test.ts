import { ApiError } from "@miles/socle-web";

import { tradsKeyError } from "./tradsKeyError";

function refusal(status: number, detail: unknown): ApiError {
  return new ApiError(status, detail);
}

describe("tradsKeyError", () => {
  it("names the invisible characters a value was refused for", () => {
    const { key, options } = tradsKeyError(
      refusal(422, { code: "direction_forcee", found: ["U+202E OVERRIDE", "U+2066 ISOLATE"] }),
    );

    expect(key).toBe("tradsKeys.errors.direction_forcee");
    expect(options.found).toBe("U+202E OVERRIDE, U+2066 ISOLATE");
  });

  it("names the culture whose value is required", () => {
    const { key, options } = tradsKeyError(
      refusal(422, { code: "valeur_par_defaut_obligatoire", culture: "fr-FR" }),
    );

    expect(key).toBe("tradsKeys.errors.valeur_par_defaut_obligatoire");
    expect(options.culture).toBe("fr-FR");
  });

  it("names the culture that is not one of the workspace's", () => {
    const { options } = tradsKeyError(
      refusal(409, { code: "culture_hors_workspace", culture: "th-TH" }),
    );

    expect(options.culture).toBe("th-TH");
  });

  it.each(["slug_pris", "cle_inconnue"])("names the slug of a %s refusal", (code) => {
    const { key, options } = tradsKeyError(refusal(409, { code, slug: "titre" }));

    expect(key).toBe(`tradsKeys.errors.${code}`);
    expect(options.slug).toBe("titre");
  });

  it("names the unreadable file", () => {
    const { options } = tradsKeyError(
      refusal(422, { code: "trads_illisible", path: "trads/accueil/fr-FR.yaml" }),
    );

    expect(options.path).toBe("trads/accueil/fr-FR.yaml");
  });

  it("distinguishes a moved branch, which loses nothing", () => {
    expect(tradsKeyError(refusal(409, { code: "branche_a_bouge" })).key).toBe(
      "tradsKeys.errors.branche_a_bouge",
    );
  });

  it("reads a plain string refusal as its own key", () => {
    expect(tradsKeyError(refusal(409, "contexte_inconnu")).key).toBe(
      "tradsKeys.errors.contexte_inconnu",
    );
  });

  it("falls back on the generic message for anything else", () => {
    expect(tradsKeyError(new Error("réseau")).key).toBe("tradsKeys.errors.unexpected");
    expect(tradsKeyError(refusal(500, {})).key).toBe("tradsKeys.errors.unexpected");
  });
});
