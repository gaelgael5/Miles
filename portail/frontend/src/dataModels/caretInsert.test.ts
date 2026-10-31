import { withInsertion } from "./caretInsert";

describe("withInsertion", () => {
  it("poses the path at the caret and puts the caret behind it", () => {
    const got = withInsertion('{ "ref":  }', "$.a.b", { start: 9, end: 9 });

    expect(got.text).toBe('{ "ref": $.a.b }');
    expect(got.caret).toBe(14);
  });

  it("replaces the selection rather than pushing the path next to it", () => {
    const got = withInsertion('{ "ref": $.vieux }', "$.a.b", { start: 9, end: 16 });

    expect(got.text).toBe('{ "ref": $.a.b }');
  });

  it("appends when the caret is unknown, rather than overwriting the beginning", () => {
    // Le curseur est perdu dès que l'éditeur n'a jamais eu le focus. Insérer en 0
    // écrirait par-dessus le début du template — perdre le curseur ne doit jamais
    // faire perdre ce qui est écrit.
    const got = withInsertion('{ "ref": 1 }', "$.a.b", null);

    expect(got.text).toBe('{ "ref": 1 }$.a.b');
    expect(got.caret).toBe(17);
  });

  it("holds a caret that points past the text", () => {
    // Le template a pu raccourcir entre la lecture du curseur et l'insertion.
    const got = withInsertion("{}", "$.a", { start: 99, end: 120 });

    expect(got.text).toBe("{}$.a");
  });

  it("holds a backwards selection", () => {
    const got = withInsertion("abcdef", "X", { start: 4, end: 2 });

    expect(got.text).toBe("abcdXef");
  });
});
