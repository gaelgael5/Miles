import { fireEvent, render, screen } from "@testing-library/react";

import "../i18n/i18n";
import type { Method } from "../api/ingestion";
import type { UploadProgress } from "../api/upload";
import { FileTrialForm } from "./FileTrialForm";

const METHODE: Method = {
  source: "magasins-import",
  storage: "magasins",
  entry_model: "pudo/magasin",
  mode: "fichier",
  path: "/ingest/magasins-import/fichier",
  operation: "/ingest/{source}/fichier",
  served: true,
  request_schema: { type: "object" },
  model_refusal: null,
  example: null,
};

function monte(progress: UploadProgress | null, onCancel = () => {}) {
  return render(
    <FileTrialForm
      method={METHODE}
      pending={progress !== null}
      progress={progress}
      onDeposit={() => {}}
      onCancel={onCancel}
    />,
  );
}

describe("la progression d'un envoi de document", () => {
  it("ne montre NI barre NI interruption avant qu'un envoi ne commence", () => {
    monte(null);

    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop the upload" })).not.toBeInTheDocument();
  });

  it("montre où en est l'envoi, en barre ET en texte", () => {
    monte({ sent: 400_000_000, total: 943_000_000 });

    const barre = screen.getByRole("progressbar", { name: "Upload progress" });
    expect(barre).toHaveAttribute("value", "400000000");
    expect(barre).toHaveAttribute("max", "943000000");
    // Le pourcentage EN TEXTE : une barre seule ne se lit ni à la voix, ni sur une
    // capture d'écran envoyée pour demander de l'aide.
    const ligne = screen.getByRole("status");
    expect(ligne).toHaveTextContent("42%");
    // Et les octets, dans la culture de l'INTERFACE, parce que « 42 % » ne dit pas s'il
    // reste une minute ou une heure.
    expect(ligne).toHaveTextContent("400 MB");
    expect(ligne).toHaveTextContent("943 MB");
  });

  it("interrompt l'envoi quand on le demande", () => {
    const abandons: number[] = [];
    monte({ sent: 10, total: 100 }, () => abandons.push(1));

    fireEvent.click(screen.getByRole("button", { name: "Stop the upload" }));

    expect(abandons).toEqual([1]);
  });

  it("montre un envoi FINI pour un document vide, et non « NaN »", () => {
    // Zéro octet sur zéro n'est pas une division qu'on fait. L'écran doit montrer un
    // envoi terminé, pour que ce qui se lise ensuite soit le refus du point d'entrée.
    monte({ sent: 0, total: 0 });

    expect(screen.getByRole("status")).toHaveTextContent("100%");
    expect(screen.getByRole("status").textContent).not.toMatch(/NaN/);
  });
});
