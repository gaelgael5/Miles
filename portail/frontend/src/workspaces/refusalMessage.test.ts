import i18n from "../i18n/i18n";
import { refusalMessage } from "./refusalMessage";

/**
 * Le défaut du 15/11/2026, et le test qui l'aurait vu : un code sans libellé s'affichait
 * en clef brute. Le repli ne remplace pas la garde du backend qui exige le libellé
 * (`test_problem_labels.py`) ; il dit ce qu'on voit si elle est un jour contournée.
 */
describe("refusalMessage", () => {
  const t = i18n.getFixedT("fr-FR");

  it("rend le libellé quand le code en a un", () => {
    const message = refusalMessage(t, "dataModels.errors.conflict.disposition_ancienne");
    expect(message).toContain("ancienne disposition");
  });

  it("dit le CODE, jamais la clef, quand le libellé manque", () => {
    const message = refusalMessage(t, "dataModels.errors.conflict.refus_sans_libelle");
    // Discriminant : la clef entière est ce qu'on voyait sur la copie d'écran.
    expect(message).not.toContain("dataModels.errors.conflict");
    expect(message).toContain("refus_sans_libelle");
  });

  it("interpole les valeurs du libellé qui en attend", () => {
    // Sans ce contrôle, poser `defaultValue` pourrait masquer les valeurs du message.
    const message = refusalMessage(t, "holds.errors.branche_tenue", { by: "Gael" });
    expect(message).toContain("Gael");
  });
});
