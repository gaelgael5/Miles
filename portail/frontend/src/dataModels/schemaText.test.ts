import { incompleteAt, parseSchema, sameSchema, targetOf } from "./schemaText";

describe("schemaText", () => {
  it("refuses a schema left incomplete by typing, naming where", () => {
    const typing = parseSchema("type: object\nproperties:\n  nom:\n    type: string\n  age:\n");

    expect(typing).toEqual({ ok: false, message: "« properties.age » n'est pas encore un schéma" });
    expect(incompleteAt({ type: "array", items: null })).toBe("items");
    expect(incompleteAt({ anyOf: [{ type: "string" }, null] })).toBe("anyOf.1");
    expect(incompleteAt({ properties: { a: { properties: { b: 3 } } } })).toBe("properties.a.properties.b");
    // Un schéma booléen est un schéma.
    expect(incompleteAt({ properties: { a: true }, additionalProperties: false })).toBeNull();
  });

  it("compares what two texts say, not their bytes", () => {
    expect(sameSchema("type: object\n", "type:   object\n")).toBe(true);
    expect(sameSchema("type: object\n", "type: array\n")).toBe(false);
  });

  it("reads a model URI", () => {
    expect(targetOf("miles:/shared/personne")).toEqual(["shared", "personne"]);
    expect(targetOf("miles:/domains/suivi/colis#/$defs/x")).toEqual(["suivi", "colis"]);
    expect(targetOf("#/$defs/x")).toBeNull();
  });
});
