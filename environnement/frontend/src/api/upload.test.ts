import { ApiError } from "@miles/socle-web";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UploadAborted, uploadWithProgress } from "./upload";

/**
 * Un `XMLHttpRequest` qu'on PILOTE, plutôt que la doublure d'API du socle.
 *
 * Celle du socle répond dans `send`, ce qui convient pour éprouver un écran mais pas pour
 * éprouver ce transport : on a besoin de tenir l'envoi ouvert, d'émettre la progression
 * qu'on veut, et d'interrompre avant la réponse.
 */
class FauxEnvoi extends EventTarget {
  static dernier: FauxEnvoi | null = null;
  status = 0;
  responseText = "";
  readonly upload = new EventTarget();
  envoye: unknown = null;
  interrompu = false;
  typeDeContenu: string | null = null;

  open(): void {
    FauxEnvoi.dernier = this;
  }

  setRequestHeader(nom: string, valeur: string): void {
    if (nom === "Content-Type") {
      this.typeDeContenu = valeur;
    }
  }

  send(body: unknown): void {
    this.envoye = body;
  }

  abort(): void {
    this.interrompu = true;
    this.dispatchEvent(new Event("abort"));
  }

  progresse(loaded: number, total: number): void {
    this.upload.dispatchEvent(
      new ProgressEvent("progress", { lengthComputable: true, loaded, total }),
    );
  }

  repond(status: number, corps: string): void {
    this.status = status;
    this.responseText = corps;
    this.dispatchEvent(new Event("load"));
  }
}

function envoi() {
  const courant = FauxEnvoi.dernier;
  if (courant === null) {
    throw new Error("aucun envoi ouvert");
  }
  return courant;
}

const DOCUMENT = new File(['{"magasins": []}'], "magasins.json", { type: "application/json" });

describe("l'envoi d'un document avec sa progression", () => {
  beforeEach(() => {
    FauxEnvoi.dernier = null;
    vi.stubGlobal("XMLHttpRequest", FauxEnvoi);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rapporte chaque avancée, puis rend la réponse décodée", async () => {
    const vues: { sent: number; total: number }[] = [];
    const promesse = uploadWithProgress<{ status: number }>(
      "/api/ingestion/try/s/fichier",
      DOCUMENT,
      "application/octet-stream",
      (avancee) => vues.push(avancee),
    );

    envoi().progresse(40, 100);
    envoi().progresse(100, 100);
    envoi().repond(200, '{"status": 202, "body": {"id": "abc"}}');

    await expect(promesse).resolves.toEqual({ status: 202, body: { id: "abc" } });
    // Les DEUX avancées, dans l'ordre : c'est ce qui fait avancer la barre, et un
    // transport qui ne rapporterait que la fin la ferait sauter de 0 à 100 %.
    expect(vues).toEqual([
      { sent: 40, total: 100 },
      { sent: 100, total: 100 },
    ]);
  });

  it("envoie le FICHIER tel quel, sans le lire", async () => {
    const promesse = uploadWithProgress("/chemin", DOCUMENT, "application/octet-stream", () => {});

    // Le `File` lui-même, et non son contenu : le navigateur le lit depuis le disque au
    // fil de l'envoi. Un `await file.text()` quelque part chargerait neuf cents
    // mégaoctets dans l'onglet, et c'est invisible sur un fichier de test.
    expect(envoi().envoye).toBe(DOCUMENT);
    expect(envoi().typeDeContenu).toBe("application/octet-stream");

    envoi().repond(200, "{}");
    await promesse;
  });

  it("ignore une avancée dont la taille n'est pas connue", async () => {
    const vues: unknown[] = [];
    const promesse = uploadWithProgress("/chemin", DOCUMENT, "application/json", (a) =>
      vues.push(a),
    );

    // `lengthComputable` faux : rapporter zéro sur zéro afficherait une barre pleine
    // avant le premier octet.
    envoi().upload.dispatchEvent(new ProgressEvent("progress", { loaded: 10, total: 0 }));
    envoi().repond(200, "{}");
    await promesse;

    expect(vues).toEqual([]);
  });

  it("rend le refus du point d'entrée, avec son code", async () => {
    const promesse = uploadWithProgress("/chemin", DOCUMENT, "application/json", () => {});

    envoi().repond(413, '{"detail": {"code": "fichier_trop_grand", "detail": "2147483648"}}');

    const erreur = await promesse.catch((raison: unknown) => raison);
    expect(erreur).toBeInstanceOf(ApiError);
    const refus = erreur as ApiError;
    expect(refus.status).toBe(413);
    // Le `detail` du contrat, lisible comme celui de n'importe quel autre appel : sans
    // cela, l'écran d'essai aurait deux formes de refus à distinguer.
    expect(refus.detail).toEqual({ code: "fichier_trop_grand", detail: "2147483648" });
  });

  it("ne jette pas quand un refus arrive sans corps lisible", async () => {
    const promesse = uploadWithProgress("/chemin", DOCUMENT, "application/json", () => {});

    // Le 413 de nginx est une page HTML : le décodage ne doit pas transformer un refus
    // en panne de l'écran. Mesuré sur la stack livrée le 07/11/2026.
    envoi().repond(413, "<html><body>413 Request Entity Too Large</body></html>");

    const erreur = (await promesse.catch((raison: unknown) => raison)) as ApiError;
    expect(erreur.status).toBe(413);
    expect(erreur.detail).toBeUndefined();
  });

  it("interrompt l'envoi quand on l'abandonne", async () => {
    const controleur = new AbortController();
    const promesse = uploadWithProgress(
      "/chemin",
      DOCUMENT,
      "application/json",
      () => {},
      controleur.signal,
    );

    controleur.abort();

    await expect(promesse).rejects.toBeInstanceOf(UploadAborted);
    // La requête est RÉELLEMENT coupée : sans cela, le point d'entrée continuerait
    // d'écrire sur le disque de la stack un document que plus personne n'attend.
    expect(envoi().interrompu).toBe(true);
  });
});
