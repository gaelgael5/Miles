import { describe, expect, it } from "vitest";

import { EVENTS_REFRESH_MS, refreshInterval } from "./events";

describe("le rafraîchissement du journal", () => {
  it("interroge la tête du journal toutes les vingt secondes", () => {
    // Le journal se regarde pendant qu'il se remplit : un import écrit un event par
    // objet rangé, donc la première page EST la progression de l'import.
    expect(refreshInterval(1)).toBe(EVENTS_REFRESH_MS);
  });

  it("ne rafraîchit AUCUNE autre page", () => {
    // Le tri va du plus récent au plus ancien : un event qui arrive pousse tout le reste
    // d'un rang, et les lignes se déplaceraient sous l'œil de celui qui les lit.
    expect(refreshInterval(2)).toBe(false);
    expect(refreshInterval(7)).toBe(false);
  });
});
